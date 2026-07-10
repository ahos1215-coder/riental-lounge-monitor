"""v2 予測テンプレート（店別・夜タイプ別の夜シェイプ × スケール）を1コマンドで再生成する。

検証済み v2 設計 = 「店別の夜シェイプ・テンプレート × スケール」。バイクオフで A(本番の
per-store LightGBM+後処理)に艦隊 MAE 7.89 vs 11.88 で勝った案。夜の軸は曜日ではなく
夜タイプ(L/M/H, oriental/ml/night_type 参照)。

各アクティブ店 (ALL_STORE_IDS ∩ 直近データのある店) について直近 ~13 週の実測を取得し、
夜(19:00-05:00, JST, -6h 規約)ごとに 15 分スロット平均を作り、夜タイプでバケット分けして
(特別期間=GW/お盆/年末年始は参照集合から除外)、per-slot の正規化シェイプ(median)＋
P10/P90 帯＋男性比＋直近6夜のスケール基準を店×タイプで算出する。出力は Storage の
forecast/templates_v2.json 1本。

v2.1（採用済み2レバー・42夜ハーネスで検証・plan/FORECAST_V2.md）:
  - blend50: 今夜のスケール = 0.5×同タイプ直近6中央値 + 0.5×グローバルLGBM(1本)。
    テンプレ生成と同ジョブで当朝に学習(拡大窓・数秒・モデルは出荷しない)し、店別 `tonight`
    ブロック {date, night_type, scale_median, scale_lgbm, scale_blend50} に書く。snapshot は
    tonight.date/night_type 一致時のみ scale_blend50 を採用（不一致は scale_ref にフォールバック）。
  - 帯 k 拡幅 + 自動再校正: P50(=shape) 中心に (P10,P90) を係数 k で拡幅（被覆率 ~80% 狙い）。
    直近スコアの band_coverage から k を毎朝 1 段だけ寄せ、meta.band_k に永続化する。

これは SHADOW（本番配信 oriental/ml/forecast_service.py は一切触らない）。テンプレは
snapshot_forecasts.py が毎晩読み込み、A スナップショットと並べて v2 予測を記録し、
score_forecasts.py が両者を実測でスコアする。

stdlib のみ。SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY が必要（ローカルは .env.local、
CI は GHA env）。秘匿値は絶対に出力しない。

  python scripts/build_templates.py            # 生成して Storage にアップロード
  python scripts/build_templates.py --dry-run  # 取得・集計してカバレッジのみ表示（無アップロード）
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

def _load_module_from_file(name: str, relpath: str):
    """パッケージ経由importが使えない最小依存環境(GHA)用のファイル直読みローダ。
    oriental/__init__.py が flask、oriental/ml/__init__.py が pandas/lightgbm を
    引き込むため、stdlib+jpholidayしか無いジョブでは対象ファイルだけを直接読む。"""
    import importlib.util

    p = REPO_ROOT / relpath
    spec = importlib.util.spec_from_file_location(name, p)
    m = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(m)
    return m


try:
    from oriental.ml.night_type import classify_night, night_date_of, special_block
    from oriental.utils.stores import ALL_STORE_IDS
except ModuleNotFoundError:
    _nt = _load_module_from_file("_night_type_standalone", "oriental/ml/night_type.py")
    classify_night, night_date_of, special_block = (
        _nt.classify_night, _nt.night_date_of, _nt.special_block,
    )
    _st = _load_module_from_file("_stores_standalone", "oriental/utils/stores.py")
    ALL_STORE_IDS = _st.ALL_STORE_IDS

# v2.1 のスケール ML(blend50)は pandas/numpy/lightgbm を使う。最小依存環境(snapshot ジョブ等)
# では欠けているので、ここは "あれば使う" 任意依存にする。無ければ tonight ブロックを省略して
# v2 ベース(scale_ref)にグレースフルに縮退する（テンプレ本体・帯校正は stdlib のみで作れる）。
try:
    import numpy as _np  # noqa: F401  (lightgbm の依存として実質必須)
    import pandas as _pd
    import lightgbm as _lgb

    _HAS_LGBM = True
except Exception:  # noqa: BLE001
    _pd = None  # type: ignore[assignment]
    _lgb = None  # type: ignore[assignment]
    _HAS_LGBM = False

JST = timezone(timedelta(hours=9))

SCHEMA = "v2t1"
TEMPLATES_PATH = "forecast/templates_v2.json"

SLOTS = 40  # 19:00〜05:00 を 15 分刻みで 40 スロット (index 0=19:00 .. 39=04:45)
NIGHT_START_HOUR = 19

FETCH_DAYS = 91  # ~13 週（M の 12 週窓 + 余白）
WINDOW_DAYS = {"L": 56, "H": 56, "M": 84}  # タイプ別ルックバック（L/H=8週, M=12週）
MIN_NIGHTS = 4  # このタイプの有効夜数がこれ未満ならフォールバック
MIN_SCALE_SAMPLE = 3  # M のスケールを M 自身で取るのに必要な最低夜数
SCALE_RECENT_N = 6  # スケール基準 = 直近この夜数の夜合計の median
SUNDAY_FACTOR = 1.20  # 実測の日曜係数（M スケールが薄いとき L スケールに掛ける）
MIN_SLOTS_PER_NIGHT = 12  # 1 夜として採用するのに必要な最低観測スロット数（欠損夜を弾く）
STALE_DAYS = 7  # 最新行がこれより古い店は carry-forward（train と同じ）

# --- v2.1 レバー1: スケールの blend50（0.5×同タイプ直近6中央値 + 0.5×グローバルLGBM）---
# 42夜ハーネス(1806 store-night)で採用済み: 艦隊 MAE 8.628→8.261(-4.3%)、H夜 -8.9%。
# 特徴量は「店(cat)・夜タイプ(cat)・同タイプ直近6の median/mean/last1」のみ。
# 不採用(禁止): payday/month/weather、LGBM 単独、乖離ガード。詳細は plan/FORECAST_V2.md。
SCALE_LGBM_MIN_PRIOR = 3   # 学習行を出すのに必要な「同タイプの過去夜」最低数（<3 はスキップ）
SCALE_LGBM_MIN_ROWS = 200  # これ未満の学習行数ならモデルを作らず tonight を省略（v2 ベースに縮退）
BLEND50_W = 0.5            # blend50 の median 重み（残りが LGBM）
SCALE_FEATURE_COLS = ["store", "night_type", "recent_median6", "recent_mean6", "recent_last1"]
SCALE_CAT_COLS = ["store", "night_type"]

# --- v2.1 レバー2: 予測帯(P10/P90)の k 拡幅＋自動再校正 ---
# k=1.7 で被覆率 61.8%→~80%。静的 k はデータ蓄積で過拡幅するため、直近スコアの
# band_coverage を読んで目標 80% へ寄せる決定論的再校正を毎朝行う。
DEFAULT_BAND_K = 1.7       # 初期/データ無しのときの k
BAND_K_MIN = 1.0           # k=1.0 は無補正（p10/p90 据え置き）
BAND_K_MAX = 2.2
BAND_RECAL_NIGHTS = 28     # 再校正で読む直近スコアの夜数（up-to-28）
BAND_COVERAGE_LOW = 0.78   # 平均被覆 < これ → k を +0.1（帯を広げる）
BAND_COVERAGE_HIGH = 0.86  # 平均被覆 > これ → k を -0.1（帯を狭める）
BAND_K_STEP = 0.1


# --------------------------------------------------------------------------- #
# 純関数（ネットワーク無し・ユニットテスト対象）
# --------------------------------------------------------------------------- #
def slot_index(hour: int, minute: int) -> int | None:
    """JST 時刻を 19:00 始まりの 15 分スロット index (0..39) に写す。窓外なら None。

    index 0 = 19:00, 39 = 04:45。05:00 以降・19:00 未満は窓外(None)。
    """
    idx = ((hour - NIGHT_START_HOUR) % 24) * 4 + (minute // 15)
    return idx if 0 <= idx < SLOTS else None


def percentile(sorted_vals: list[float], q: float) -> float:
    """線形補間の百分位（numpy 相当）。sorted_vals は昇順、q は 0..100。"""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    pos = (q / 100.0) * (len(sorted_vals) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return float(sorted_vals[lo])
    frac = pos - lo
    return float(sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac)


def _num(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def _parse_ts_jst(s: Any) -> datetime | None:
    """logs.ts (ISO 文字列) を naive JST datetime に変換。tz 無しは UTC 前提。"""
    if not isinstance(s, str) or not s.strip():
        return None
    try:
        dt = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(JST).replace(tzinfo=None)


def build_night_curves(rows: list[dict]) -> dict[date, dict[int, dict[str, float]]]:
    """実測行を夜(night_date) × スロット index の平均に畳む。

    Returns: {night_date: {slot_idx: {"total": x, "men": y?, "women": z?}}}
    同一スロットに複数行(5分粒度など)があれば平均。19:00-05:00 窓外の行は無視。
    """
    acc: dict[date, dict[int, dict[str, list[float]]]] = {}
    for r in rows:
        dt = _parse_ts_jst(r.get("ts"))
        if dt is None:
            continue
        idx = slot_index(dt.hour, dt.minute)
        if idx is None:
            continue
        tot = _num(r.get("total"))
        men = _num(r.get("men"))
        women = _num(r.get("women"))
        if tot is None and men is not None and women is not None:
            tot = men + women
        if tot is None:
            continue
        nd = night_date_of(dt)
        slot = acc.setdefault(nd, {}).setdefault(idx, {"t": [], "m": [], "w": []})
        slot["t"].append(tot)
        if men is not None:
            slot["m"].append(men)
        if women is not None:
            slot["w"].append(women)
    nights: dict[date, dict[int, dict[str, float]]] = {}
    for nd, slots in acc.items():
        collapsed: dict[int, dict[str, float]] = {}
        for idx, v in slots.items():
            entry: dict[str, float] = {"total": sum(v["t"]) / len(v["t"])}
            if v["m"]:
                entry["men"] = sum(v["m"]) / len(v["m"])
            if v["w"]:
                entry["women"] = sum(v["w"]) / len(v["w"])
            collapsed[idx] = entry
        nights[nd] = collapsed
    return nights


def reference_nights(
    nights: dict[date, dict[int, dict[str, float]]],
) -> list[tuple[date, dict[int, dict[str, float]]]]:
    """テンプレ参照に使える夜のリスト（特別期間 GW/お盆/年末年始を除外・新しい順）。"""
    out = [(nd, slots) for nd, slots in nights.items() if special_block(nd) is None]
    out.sort(key=lambda x: x[0], reverse=True)
    return out


def build_template(
    night_list: list[tuple[date, dict[int, dict[str, float]]]],
) -> dict[str, Any] | None:
    """夜のリスト(新しい順)から店×タイプのテンプレートを1つ作る。データ無しなら None。

    - shape[40]: 各夜を夜合計で正規化した曲線の per-slot median を、合計 1.0 に再正規化。
    - p10[40]/p90[40]: 正規化曲線の per-slot 10/90 百分位（帯・再正規化しない）。
    - men_ratio[40]: men/(men+women) の per-slot median、サンプル無しは 0.5。
    - scale_ref: 直近 6 夜の夜合計の median。
    - n_nights: 採用した有効夜数（MIN_SLOTS_PER_NIGHT 未満・夜合計 0 の夜は除外後）。
    """
    curves: list[tuple[date, list[float], float]] = []
    ratio_samples: list[list[float]] = [[] for _ in range(SLOTS)]
    for nd, slots in night_list:
        vec = [0.0] * SLOTS
        present = 0
        for idx, e in slots.items():
            if not (0 <= idx < SLOTS):
                continue
            vec[idx] = float(e.get("total") or 0.0)
            present += 1
            men = e.get("men")
            women = e.get("women")
            if men is not None and women is not None and (men + women) > 0:
                ratio_samples[idx].append(men / (men + women))
        if present < MIN_SLOTS_PER_NIGHT:
            continue  # 部分観測/欠損夜は弾く
        s = sum(vec)
        if s <= 0:
            continue
        curves.append((nd, vec, s))

    n = len(curves)
    if n == 0:
        return None

    norm = [[vec[i] / s for i in range(SLOTS)] for (_, vec, s) in curves]
    shape_raw = [median([norm[k][i] for k in range(n)]) for i in range(SLOTS)]
    ss = sum(shape_raw)
    shape = [x / ss for x in shape_raw] if ss > 0 else [1.0 / SLOTS] * SLOTS
    p10 = [percentile(sorted(norm[k][i] for k in range(n)), 10) for i in range(SLOTS)]
    p90 = [percentile(sorted(norm[k][i] for k in range(n)), 90) for i in range(SLOTS)]
    men_ratio = [
        (median(ratio_samples[i]) if ratio_samples[i] else 0.5) for i in range(SLOTS)
    ]
    recent_sums = [s for (_, _, s) in curves[:SCALE_RECENT_N]]
    scale_ref = float(median(recent_sums))

    return {
        "shape": [round(x, 6) for x in shape],
        "p10": [round(x, 6) for x in p10],
        "p90": [round(x, 6) for x in p90],
        "men_ratio": [round(x, 6) for x in men_ratio],
        "scale_ref": round(scale_ref, 3),
        "n_nights": n,
    }


def bucket_nights(
    night_list: list[tuple[date, dict[int, dict[str, float]]]],
    today: date,
) -> tuple[dict[str, list], list]:
    """参照夜(特別期間除外済み)をタイプ別窓に分ける。all は窓無し(全取得夜)で never-empty 用。"""
    buckets: dict[str, list] = {"L": [], "M": [], "H": []}
    for nd, slots in night_list:
        age = (today - nd).days
        if age < 0:
            continue
        t = classify_night(nd)
        if age <= WINDOW_DAYS[t]:
            buckets[t].append((nd, slots))
    for k in buckets:
        buckets[k].sort(key=lambda x: x[0], reverse=True)
    allb = sorted(night_list, key=lambda x: x[0], reverse=True)
    return buckets, allb


def build_store_templates(
    night_list: list[tuple[date, dict[int, dict[str, float]]]],
    today: date,
) -> dict[str, Any] | None:
    """店の参照夜から L/M/H テンプレを組む。フォールバック梯子込み。全滅なら None。

    梯子:
      - L: L 夜 >=4 → L。不足 → all-type(never empty)。
      - H: H 夜 >=4 → H。不足 → all-type。all も無ければ L を流用。
      - M: M 夜 >=4 → M。不足 → L シェイプ + スケール(M 夜>=3 なら M 自身の直近6、
           それ未満は L スケール × 1.20 実測日曜係数)。
    """
    buckets, allb = bucket_nights(night_list, today)
    all_tmpl = build_template(allb)

    out: dict[str, Any] = {}

    # --- L ---
    lt = build_template(buckets["L"])
    if lt and lt["n_nights"] >= MIN_NIGHTS:
        lt["fallback"] = None
        out["L"] = lt
    elif all_tmpl:
        ft = dict(all_tmpl)
        ft["fallback"] = "all_type"
        out["L"] = ft
    else:
        return None  # 有効夜が1つも無い → 呼び出し側で carry-forward

    # --- H ---
    ht = build_template(buckets["H"])
    if ht and ht["n_nights"] >= MIN_NIGHTS:
        ht["fallback"] = None
        out["H"] = ht
    elif all_tmpl:
        ft = dict(all_tmpl)
        ft["fallback"] = "all_type"
        out["H"] = ft
    else:
        ft = dict(out["L"])
        ft["fallback"] = "L_all"
        out["H"] = ft

    # --- M ---
    mt = build_template(buckets["M"])
    if mt and mt["n_nights"] >= MIN_NIGHTS:
        mt["fallback"] = None
        out["M"] = mt
    else:
        base = out["L"]
        m_count = mt["n_nights"] if mt else 0
        if mt and mt["n_nights"] >= MIN_SCALE_SAMPLE:
            scale = mt["scale_ref"]
            fb = "L_shape+M_scale"
        else:
            scale = round(base["scale_ref"] * SUNDAY_FACTOR, 3)
            fb = "L_shape+L_scale_x1.2"
        out["M"] = {
            "shape": list(base["shape"]),
            "p10": list(base["p10"]),
            "p90": list(base["p90"]),
            "men_ratio": list(base["men_ratio"]),
            "scale_ref": scale,
            "n_nights": m_count,
            "fallback": fb,
        }

    return out


# --------------------------------------------------------------------------- #
# v2.1 レバー2: 予測帯の k 拡幅と自動再校正（純関数・ネットワーク無し）
# --------------------------------------------------------------------------- #
def widen_band(
    shape: list[float], p10: list[float], p90: list[float], k: float
) -> tuple[list[float], list[float]]:
    """P50(=shape) を中心に (P10,P90) を係数 k で拡幅する。

        p10' = p50 − k×(p50 − p10)   （0 で下限クリップ）
        p90' = p50 + k×(p90 − p50)

    k=1.0 は無補正（p10/p90 据え置き）。p50=shape は一切動かさない。
    """
    n = min(len(shape), len(p10), len(p90))
    p10w = [max(0.0, shape[i] - k * (shape[i] - p10[i])) for i in range(n)]
    p90w = [shape[i] + k * (p90[i] - shape[i]) for i in range(n)]
    return p10w, p90w


def recalibrate_k(prev_k: float | None, coverages: list[float]) -> float:
    """直近の band_coverage 平均から k を目標 80% へ 1 段寄せる決定論ルール。

    平均被覆 < BAND_COVERAGE_LOW → k+=step（広げる）、> BAND_COVERAGE_HIGH → k-=step（狭める）。
    coverages が空（スコア未蓄積）のときは prev_k（無ければ DEFAULT_BAND_K）を据え置く。
    最後に [BAND_K_MIN, BAND_K_MAX] にクランプ。
    """
    k = DEFAULT_BAND_K if prev_k is None else float(prev_k)
    if coverages:
        mean_cov = sum(coverages) / len(coverages)
        if mean_cov < BAND_COVERAGE_LOW:
            k += BAND_K_STEP
        elif mean_cov > BAND_COVERAGE_HIGH:
            k -= BAND_K_STEP
    return round(max(BAND_K_MIN, min(BAND_K_MAX, k)), 4)


def apply_band_calibration(store_tmpl: dict[str, Any], k: float) -> None:
    """1 店の L/M/H テンプレの p10/p90 を k 拡幅で置き換える（in-place・冪等ではない）。

    生の p10/p90 に対して1回だけ適用すること（carry-forward 済みの店には再適用しない）。
    """
    for t in ("L", "M", "H"):
        tt = store_tmpl.get(t)
        if not isinstance(tt, dict):
            continue
        shape = tt.get("shape") or []
        p10 = tt.get("p10") or []
        p90 = tt.get("p90") or []
        p10w, p90w = widen_band(shape, p10, p90, k)
        tt["p10"] = [round(x, 6) for x in p10w]
        tt["p90"] = [round(x, 6) for x in p90w]


# --------------------------------------------------------------------------- #
# v2.1 レバー1: スケールの blend50（同タイプ直近6中央値 × グローバルLGBM）
# --------------------------------------------------------------------------- #
def _night_scale_samples(
    ref_nights: list[tuple[date, dict[int, dict[str, float]]]],
) -> list[dict[str, Any]]:
    """参照夜(特別期間除外済み)から、LGBM 用の「夜合計サンプル」を時系列昇順で作る。

    有効夜 = 観測スロット >= MIN_SLOTS_PER_NIGHT かつ 夜合計 > 0（build_template と同一基準）。
    各要素: {"date": date, "night_type": 'L'|'M'|'H', "total": 夜合計}。古い順に並べて返す。
    """
    samples: list[dict[str, Any]] = []
    for nd, slots in ref_nights:
        present = 0
        total = 0.0
        for idx, e in slots.items():
            if 0 <= idx < SLOTS:
                present += 1
                total += float(e.get("total") or 0.0)
        if present < MIN_SLOTS_PER_NIGHT or total <= 0:
            continue
        samples.append({"date": nd, "night_type": classify_night(nd), "total": total})
    samples.sort(key=lambda s: s["date"])
    return samples


def _scale_features(store_id: str, night_type: str, prior_totals: list[float]) -> dict[str, Any]:
    """1 予測点(店×夜タイプ)のスケール特徴量。prior_totals は同タイプの過去夜合計(古い順)。

    直近 SCALE_RECENT_N(=6) 夜の median/mean/last1 を作る。空なら NaN（LGBM は欠損を扱える）。
    """
    recents = prior_totals[-SCALE_RECENT_N:]
    if recents:
        med = float(median(recents))
        mean = float(sum(recents) / len(recents))
        last1 = float(recents[-1])
    else:
        med = mean = last1 = float("nan")
    return {
        "store": store_id,
        "night_type": night_type,
        "recent_median6": med,
        "recent_mean6": mean,
        "recent_last1": last1,
    }


def build_scale_training_rows(scale_samples: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """全店の夜合計サンプルから LGBM 学習行を作る（拡大窓・リーク無し）。

    店ごとに時系列で走査し、各夜 N について「N より前の同タイプ夜」だけで特徴量を作る。
    同タイプ過去夜が SCALE_LGBM_MIN_PRIOR(=3) 未満の行はスキップ。target = その夜の夜合計。
    """
    rows: list[dict[str, Any]] = []
    for store_id, samples in scale_samples.items():
        prior_by_type: dict[str, list[float]] = {}
        for s in samples:
            t = s["night_type"]
            prior = prior_by_type.setdefault(t, [])
            if len(prior) >= SCALE_LGBM_MIN_PRIOR:
                feat = _scale_features(store_id, t, prior)
                feat["target"] = float(s["total"])
                rows.append(feat)
            prior.append(float(s["total"]))
    return rows


def train_scale_model(rows: list[dict[str, Any]]):
    """グローバル LGBM(1本)を全店の学習行で訓練。lightgbm/pandas 不在 or 行不足なら None。

    目的=MAE、拡大窓（呼び出し側が当朝の全履歴を渡す）。返り値は (model, cat_dtypes)。
    """
    if not _HAS_LGBM or len(rows) < SCALE_LGBM_MIN_ROWS:
        return None
    df = _pd.DataFrame(rows)
    X = df[SCALE_FEATURE_COLS].copy()
    for c in SCALE_CAT_COLS:
        X[c] = X[c].astype("category")
    y = df["target"].to_numpy(dtype=float)
    dtrain = _lgb.Dataset(X, label=y, categorical_feature=SCALE_CAT_COLS, free_raw_data=False)
    params = dict(
        objective="regression_l1",
        metric="mae",
        num_leaves=15,
        max_depth=4,
        min_data_in_leaf=15,
        learning_rate=0.05,
        feature_fraction=0.8,
        bagging_fraction=0.8,
        bagging_freq=1,
        verbose=-1,
        seed=42,
    )
    model = _lgb.train(params, dtrain, num_boost_round=300)
    cat_dtypes = {c: X[c].dtype for c in SCALE_CAT_COLS}
    return model, cat_dtypes


def predict_scale_lgbm(model, cat_dtypes: dict[str, Any], feat: dict[str, Any]) -> float:
    """学習済みモデルで 1 予測点のスケール(夜合計)を推定（負値は 0 でクリップ）。"""
    row = _pd.DataFrame([feat])[SCALE_FEATURE_COLS]
    for c in SCALE_CAT_COLS:
        row[c] = row[c].astype(cat_dtypes[c])
    p = float(model.predict(row)[0])
    return max(p, 0.0)


def build_tonight_scales(
    model,
    cat_dtypes: dict[str, Any],
    store_id: str,
    tonight_type: str,
    samples: list[dict[str, Any]],
    scale_median: float,
) -> dict[str, Any]:
    """今夜(tonight_type)のスケールを推定し {scale_median, scale_lgbm, scale_blend50} を返す。

    recents は同タイプの過去夜合計（古い順）。scale_median は該当タイプの scale_ref を渡す
    （snapshot のフォールバック値と一致させ、blend50 を「フォールバックと LGBM の内挿」にする）。
    """
    prior_totals = [s["total"] for s in samples if s["night_type"] == tonight_type]
    feat = _scale_features(store_id, tonight_type, prior_totals)
    scale_lgbm = predict_scale_lgbm(model, cat_dtypes, feat)
    scale_blend50 = BLEND50_W * float(scale_median) + (1.0 - BLEND50_W) * scale_lgbm
    return {
        "scale_median": round(float(scale_median), 3),
        "scale_lgbm": round(scale_lgbm, 3),
        "scale_blend50": round(scale_blend50, 3),
    }


# --------------------------------------------------------------------------- #
# I/O（環境・Supabase）
# --------------------------------------------------------------------------- #
def _load_env() -> None:
    for name in (".env", ".env.local"):
        p = REPO_ROOT / name
        if not p.is_file():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _storage_get(bucket: str, path: str, url: str, key: str) -> bytes | None:
    endpoint = f"{url}/storage/v1/object/{bucket}/{path}"
    req = urllib.request.Request(
        endpoint, headers={"apikey": key, "Authorization": f"Bearer {key}"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        if exc.code == 400:
            try:
                body = exc.read().decode("utf-8", "replace").lower()
            except Exception:  # noqa: BLE001
                body = ""
            if "not_found" in body or "not found" in body:
                return None
        raise


def _storage_put(bucket: str, path: str, payload: bytes, url: str, key: str) -> None:
    endpoint = f"{url}/storage/v1/object/{bucket}/{path}"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "x-upsert": "true",
        "Content-Type": "application/json",
    }
    req = urllib.request.Request(endpoint, data=payload, method="POST", headers=headers)
    urllib.request.urlopen(req, timeout=30)


def _recent_night_dates(bucket: str, url: str, key: str) -> list[str]:
    """accuracy/scores/summary.json の nights(新しい順) から夜次日付リストを返す。無ければ空。"""
    raw = _storage_get(bucket, "accuracy/scores/summary.json", url, key)
    if raw is None:
        return []
    try:
        doc = json.loads(raw.decode())
    except Exception:  # noqa: BLE001
        return []
    nights = doc.get("nights") if isinstance(doc, dict) else None
    if not isinstance(nights, list):
        return []
    return [n.get("night_date") for n in nights if isinstance(n, dict) and n.get("night_date")]


def _read_recent_band_coverages(
    bucket: str, url: str, key: str, night_dates: list[str]
) -> list[float]:
    """直近 up-to-BAND_RECAL_NIGHTS 夜の scores/<date>.json から艦隊 v2 band_coverage を集める。

    取得失敗・欠損夜はスキップ。存在するものだけの float リストを返す（k 再校正の入力）。
    """
    covs: list[float] = []
    for d in night_dates[:BAND_RECAL_NIGHTS]:
        raw = _storage_get(bucket, f"accuracy/scores/{d}.json", url, key)
        if raw is None:
            continue
        try:
            doc = json.loads(raw.decode())
        except Exception:  # noqa: BLE001
            continue
        sc = doc.get("scorecard") if isinstance(doc, dict) else None
        v2 = sc.get("v2") if isinstance(sc, dict) else None
        cov = v2.get("band_coverage") if isinstance(v2, dict) else None
        if isinstance(cov, (int, float)) and not isinstance(cov, bool):
            covs.append(float(cov))
    return covs


def _fetch_store_rows(url: str, key: str, store_id: str, start_iso: str) -> list[dict]:
    """1 店の直近 FETCH_DAYS 分の実測を ts.asc キーセットで取得（1000 行/ページ）。

    PostgREST は 1 リクエスト最大 1000 行。ts.asc + ts=gt.<cursor> で O(1)/ページ。
    1 店では ts は実質ユニーク（1 計測=1 タイムスタンプ）なので gt 境界でのロスは無い。
    一過性の 5xx/429/ネットワークエラーはリトライ。
    """
    endpoint = f"{url}/rest/v1/logs"
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "Accept": "application/json"}
    rows: list[dict] = []
    cursor: str | None = None
    while True:
        params = [
            ("select", "ts,total,men,women"),
            ("store_id", f"eq.{store_id}"),
            ("ts", f"gte.{start_iso}"),
            ("order", "ts.asc"),
            ("limit", "1000"),
        ]
        if cursor is not None:
            params.append(("ts", f"gt.{cursor}"))
        full = endpoint + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(full, headers=headers)

        payload = None
        last_err = ""
        for attempt in range(1, 5):
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    payload = json.loads(resp.read().decode())
                break
            except urllib.error.HTTPError as exc:
                last_err = f"status={exc.code}"
                if exc.code < 500 and exc.code != 429:
                    # 4xx(除く429)は恒久エラー。ここで打ち切り（呼び出し側で空扱い）。
                    print(f"[build-templates][fetch] {store_id} permanent error {last_err}")
                    return rows
            except Exception as exc:  # noqa: BLE001
                last_err = str(exc)[:120]
            if attempt < 4:
                time.sleep(min(2 ** attempt, 10))
        if not isinstance(payload, list):
            print(f"[build-templates][fetch] {store_id} gave up after retries ({last_err})")
            break
        if not payload:
            break
        rows.extend(r for r in payload if isinstance(r, dict))
        if len(payload) < 1000:
            break
        cursor = payload[-1].get("ts")
        if not cursor:
            break
    return rows


def _newest_ts(rows: list[dict]) -> datetime | None:
    newest: datetime | None = None
    for r in rows:
        dt = _parse_ts_jst(r.get("ts"))
        if dt is not None and (newest is None or dt > newest):
            newest = dt
    return newest


def _carry_forward(store_id: str, prev_stores: dict, out_stores: dict, carried: list) -> bool:
    prev = prev_stores.get(store_id)
    if isinstance(prev, dict):
        out_stores[store_id] = prev
        carried.append(store_id)
        return True
    return False


def _type_summary(entry: dict, t: str) -> str:
    tt = entry.get(t) or {}
    n = tt.get("n_nights", 0)
    fb = tt.get("fallback")
    return f"{t}={n}{'*' + fb if fb else ''}"


def _write_step_summary(
    built: dict, carried: list, omitted: list, generated_at: str, dry_run: bool
) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    lines = [f"## Build forecast v2 templates ({'dry-run' if dry_run else 'upload'})\n\n"]
    lines.append(f"- generated_at: {generated_at}\n")
    lines.append(
        f"- stores built: **{len(built)}**, carried-forward: **{len(carried)}**, "
        f"omitted: **{len(omitted)}**\n\n"
    )
    lines.append("| store | L (n*fb) | M (n*fb) | H (n*fb) |\n|---|---|---|---|\n")
    for sid in sorted(built):
        e = built[sid]
        lines.append(
            f"| {sid} | {_type_summary(e, 'L')} | {_type_summary(e, 'M')} | {_type_summary(e, 'H')} |\n"
        )
    if carried:
        lines.append(f"\ncarried-forward: {', '.join(sorted(carried))}\n")
    if omitted:
        lines.append(f"\nomitted (no data & no prior): {', '.join(sorted(omitted))}\n")
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("".join(lines))
    except Exception as exc:  # noqa: BLE001
        print(f"[build-templates] step summary write failed: {str(exc)[:120]}")


def main() -> int:
    _load_env()
    parser = argparse.ArgumentParser(description="Build v2 forecast templates and upload to Storage.")
    parser.add_argument("--dry-run", action="store_true", help="集計のみ・Storage へアップロードしない")
    args = parser.parse_args()

    supabase_url = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_SERVICE_KEY") or ""
    bucket = (os.environ.get("FORECAST_MODEL_BUCKET") or "ml-models").strip()
    if not supabase_url or not key:
        raise SystemExit("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")

    now = datetime.now(JST)
    today = now.date()
    start_iso = (datetime.now(timezone.utc) - timedelta(days=FETCH_DAYS)).isoformat()

    # 既存テンプレを1度だけ取得（stale/no-data 店の carry-forward 用 + 前回の band_k）。
    prev_stores: dict[str, Any] = {}
    prev_k: float | None = None
    raw_prev = _storage_get(bucket, TEMPLATES_PATH, supabase_url, key)
    if raw_prev is not None:
        try:
            prev_doc = json.loads(raw_prev.decode())
            if isinstance(prev_doc, dict) and isinstance(prev_doc.get("stores"), dict):
                prev_stores = prev_doc["stores"]
            prev_meta = prev_doc.get("meta") if isinstance(prev_doc, dict) else None
            if isinstance(prev_meta, dict) and isinstance(prev_meta.get("band_k"), (int, float)):
                prev_k = float(prev_meta["band_k"])
        except Exception:  # noqa: BLE001
            print("[build-templates] existing templates_v2.json unparseable; ignoring for carry-forward")

    built: dict[str, Any] = {}
    carried: list[str] = []
    omitted: list[str] = []
    fresh: list[str] = []                       # 今回フレッシュに作った店（帯校正 + tonight の対象）
    scale_samples: dict[str, list[dict[str, Any]]] = {}  # store_id -> 夜合計サンプル(古い順)

    for store_id in ALL_STORE_IDS:
        rows = _fetch_store_rows(supabase_url, key, store_id, start_iso)
        if not rows:
            if _carry_forward(store_id, prev_stores, built, carried):
                print(f"[build-templates] {store_id}: no data -> carried forward")
            else:
                omitted.append(store_id)
                print(f"[build-templates][warn] {store_id}: no data and no prior template -> omitted")
            continue

        newest = _newest_ts(rows)
        if newest is not None and (now.replace(tzinfo=None) - newest) > timedelta(days=STALE_DAYS):
            if _carry_forward(store_id, prev_stores, built, carried):
                print(f"[build-templates] {store_id}: stale (last={newest.date()}) -> carried forward")
                continue
            print(f"[build-templates][warn] {store_id}: stale (last={newest.date()}) but no prior -> building anyway")

        nights = build_night_curves(rows)
        ref = reference_nights(nights)
        tmpl = build_store_templates(ref, today)
        if tmpl is None:
            if _carry_forward(store_id, prev_stores, built, carried):
                print(f"[build-templates] {store_id}: no valid nights -> carried forward")
            else:
                omitted.append(store_id)
                print(f"[build-templates][warn] {store_id}: no valid nights and no prior -> omitted")
            continue

        built[store_id] = tmpl
        fresh.append(store_id)
        scale_samples[store_id] = _night_scale_samples(ref)
        print(
            f"[build-templates] {store_id}: "
            f"{_type_summary(tmpl, 'L')} {_type_summary(tmpl, 'M')} {_type_summary(tmpl, 'H')}"
        )

    if not built:
        raise SystemExit("[build-templates] catastrophic: zero stores built (check Supabase creds / data)")

    # --- v2.1 レバー2: 帯 k の自動再校正 + フレッシュ店へ拡幅適用 ---
    # carry-forward 店は前回の校正済み帯をそのまま保持（再拡幅しない＝多重拡幅の防止）。
    coverages: list[float] = []
    try:
        cov_dates = _recent_night_dates(bucket, supabase_url, key)
        coverages = _read_recent_band_coverages(bucket, supabase_url, key, cov_dates)
    except Exception as exc:  # noqa: BLE001
        print(f"[build-templates][warn] band coverage read failed: {str(exc)[:120]}")
    band_k = recalibrate_k(prev_k, coverages)
    band_cov_mean = round(sum(coverages) / len(coverages), 4) if coverages else None
    for sid in fresh:
        apply_band_calibration(built[sid], band_k)
    print(
        f"[build-templates] band_k={band_k} (prev={prev_k}, "
        f"coverage_28d={band_cov_mean} over {len(coverages)} nights)"
    )

    # --- v2.1 レバー1: グローバル LGBM を全フレッシュ店の全履歴で学習し、今夜のスケールを推定 ---
    tonight_type = classify_night(today)
    tonight_built = 0
    training_rows = build_scale_training_rows({s: scale_samples[s] for s in fresh})
    trained = train_scale_model(training_rows)
    if trained is None:
        if not _HAS_LGBM:
            print("[build-templates][warn] lightgbm/pandas 不在 → tonight(blend50) を省略（v2 ベースで継続）")
        else:
            print(f"[build-templates][warn] 学習行 {len(training_rows)} < {SCALE_LGBM_MIN_ROWS} → tonight を省略")
    else:
        model, cat_dtypes = trained
        for sid in fresh:
            type_tmpl = built[sid].get(tonight_type)
            if not isinstance(type_tmpl, dict):
                continue
            scale_median = float(type_tmpl.get("scale_ref") or 0.0)
            tonight = build_tonight_scales(
                model, cat_dtypes, sid, tonight_type, scale_samples[sid], scale_median
            )
            tonight["date"] = today.isoformat()
            tonight["night_type"] = tonight_type
            built[sid]["tonight"] = tonight
            tonight_built += 1
        print(
            f"[build-templates] tonight={tonight_type} scales built for {tonight_built} stores "
            f"(LGBM trained on {len(training_rows)} rows)"
        )

    generated_at = datetime.now(timezone.utc).isoformat()
    doc = {
        "schema": SCHEMA,
        "generated_at": generated_at,
        "stores": built,
        "meta": {
            "band_k": band_k,
            "band_coverage_28d": band_cov_mean,
            "band_nights_used": len(coverages),
            "tonight_type": tonight_type,
            "tonight_scale_source": "blend50" if tonight_built else "scale_ref",
        },
    }

    print(
        f"[build-templates] summary: built={len(built)} "
        f"(carried_forward={len(carried)}) omitted={len(omitted)} total_stores={len(ALL_STORE_IDS)}"
    )

    if args.dry_run:
        print("[build-templates] --dry-run: NOT uploading. Coverage per store:")
        for sid in sorted(built):
            e = built[sid]
            print(f"    {sid:<18} {_type_summary(e,'L'):<16} {_type_summary(e,'M'):<20} {_type_summary(e,'H')}")
        print(f"\n[build-templates] --dry-run: band_k={band_k}  tonight_type={tonight_type}")
        print("[build-templates] --dry-run: tonight scales (median / lgbm / blend50):")
        for sid in sorted(built):
            tn = built[sid].get("tonight")
            if isinstance(tn, dict):
                print(
                    f"    {sid:<18} median={tn['scale_median']:>10.2f}  "
                    f"lgbm={tn['scale_lgbm']:>10.2f}  blend50={tn['scale_blend50']:>10.2f}"
                )
        _write_step_summary(built, carried, omitted, generated_at, dry_run=True)
        return 0

    _storage_put(
        bucket, TEMPLATES_PATH, json.dumps(doc, ensure_ascii=False).encode("utf-8"), supabase_url, key
    )
    print(f"[build-templates] uploaded {len(built)} stores -> {bucket}/{TEMPLATES_PATH}")
    _write_step_summary(built, carried, omitted, generated_at, dry_run=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
