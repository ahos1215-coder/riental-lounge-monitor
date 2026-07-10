"""Daily answer-check: score last night's snapshotted forecast against the actual
19:00–05:00 counts, per store.

Runs ~06:10 JST (after the night ends at 05:00). For each store it aligns the
snapshot's predicted curve with the realized `logs` totals on the same 15-minute
slots and computes the LIVE forecast MAE — the real-world error users experienced,
distinct from the training holdout MAE. Results are written per-night and appended
to a rolling summary in Supabase Storage so error can be tracked over time (and the
impact of changes like the weather fix can be seen as a real-world number).
See plan/FORECAST_ACCURACY.md.

Storage layout (reuses the existing model bucket):
    <bucket>/accuracy/snapshots/<YYYYMMDD>.json  (written by snapshot_forecasts.py)
    <bucket>/accuracy/scores/<YYYYMMDD>.json
    <bucket>/accuracy/scores/summary.json        (rolling, newest first)

Stdlib only. Requires SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
JST = timezone(timedelta(hours=9))
SLOT_MIN = 15
SUMMARY_KEEP = 60
FETCH_PAGE_SIZE = 1000     # PostgREST 1リクエスト最大行数と揃える（build_templates.pyと同一）
FETCH_ABSURD_ROWS = 50_000  # 1店・1夜でこれを超えたら暴走クエリを疑い、大声で警告する


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


def _parse_iso(s: str) -> datetime | None:
    if not isinstance(s, str) or not s.strip():
        return None
    t = s.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _slot_key(dt: datetime) -> str:
    """Floor a datetime to the JST 15-minute slot; stable string key."""
    j = dt.astimezone(JST)
    j = j.replace(minute=(j.minute // SLOT_MIN) * SLOT_MIN, second=0, microsecond=0)
    return j.strftime("%Y-%m-%dT%H:%M")


def _storage_get(bucket: str, path: str, url: str, key: str) -> bytes | None:
    endpoint = f"{url}/storage/v1/object/{bucket}/{path}"
    req = urllib.request.Request(endpoint, headers={"apikey": key, "Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        # Supabase Storage は存在しないオブジェクトに対し HTTP 400 + body {"error":"not_found",...}
        # を返すことがある（初回でスナップショット/サマリが未作成のケース）。これは「無い」扱いで None。
        if exc.code == 400:
            try:
                body = exc.read().decode("utf-8", "replace").lower()
            except Exception:  # noqa: BLE001
                body = ""
            if "not_found" in body or "not found" in body or "object not found" in body:
                return None
        raise


def _storage_put(bucket: str, path: str, payload: bytes, url: str, key: str) -> None:
    endpoint = f"{url}/storage/v1/object/{bucket}/{path}"
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "x-upsert": "true", "Content-Type": "application/json"}
    req = urllib.request.Request(endpoint, data=payload, method="POST", headers=headers)
    urllib.request.urlopen(req, timeout=30)


def _fetch_actuals(url: str, key: str, store_id: str, start_iso: str, end_iso: str) -> list[dict]:
    """1店・1ウィンドウ分の実測行を ts.asc キーセットページネーションで全件取得する。

    以前は limit=5000 の単発フェッチだったため、1 夜の行数がそれを超えると
    サイレントに切り捨てられ、答え合わせ(A vs v2 scoring)が静かに壊れる恐れがあった。
    scripts/build_templates.py の _fetch_store_rows と同じ規約
    (ts=gt.<cursor> で 1000 行/ページ、短いページで終了)を採用する。
    select/フィルタ(store_id・gte/lte の時間窓)/order は完全不変、完全性だけを直す。
    """
    endpoint = f"{url}/rest/v1/logs"
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "Accept": "application/json"}
    rows: list[dict] = []
    cursor: str | None = None
    pages = 0
    while True:
        params = [
            ("select", "ts,total,men,women"),
            ("store_id", f"eq.{store_id}"),
            ("ts", f"gte.{start_iso}" if cursor is None else f"gt.{cursor}"),
            ("ts", f"lte.{end_iso}"),
            ("order", "ts.asc"),
            ("limit", str(FETCH_PAGE_SIZE)),
        ]
        full = endpoint + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(full, headers=headers)

        payload = None
        for attempt in range(1, 4):
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    payload = json.loads(resp.read().decode())
                break
            except Exception:  # noqa: BLE001
                if attempt < 3:
                    time.sleep(2 * attempt)
        pages += 1
        if not isinstance(payload, list):
            print(f"[score][fetch] {store_id}: page {pages} gave up after retries — stopping pagination.")
            break
        rows.extend(r for r in payload if isinstance(r, dict))
        if len(payload) < FETCH_PAGE_SIZE:
            break
        cursor = payload[-1].get("ts")
        if not cursor:
            break

    print(f"[score][fetch] {store_id}: rows={len(rows)} pages={pages}")
    if len(rows) > FETCH_ABSURD_ROWS:
        print(
            f"[score][fetch][WARN] {store_id}: {len(rows)} rows for a single window "
            f"(> {FETCH_ABSURD_ROWS}) — possible runaway query / bad date filter, investigate."
        )
    return rows


def _actual_total(row: dict) -> float | None:
    for k in ("total",):
        v = row.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    men, women = row.get("men"), row.get("women")
    try:
        if men is not None and women is not None:
            return float(men) + float(women)
    except (TypeError, ValueError):
        pass
    return None


def _slot_means(rows: list[dict]) -> dict[str, float]:
    """Average actual total per 15-min JST slot (multiple 5-min rows collapse into one)."""
    by_slot: dict[str, list[float]] = {}
    for r in rows:
        dt = _parse_iso(r.get("ts", ""))
        tot = _actual_total(r)
        if dt is None or tot is None:
            continue
        by_slot.setdefault(_slot_key(dt), []).append(tot)
    return {k: sum(v) / len(v) for k, v in by_slot.items()}


def _alert(message: str) -> None:
    """Post to OPS_NOTIFY_WEBHOOK_URL (Slack/Discord); no-op if unset. This is the
    'Act' in the answer-check PDCA loop: when the live forecast degrades or stops
    beating the naive baseline in production, ping a human to investigate/retrain."""
    url = (os.environ.get("OPS_NOTIFY_WEBHOOK_URL") or "").strip()
    if not url:
        print("[score][alert] (OPS_NOTIFY_WEBHOOK_URL unset) " + message)
        return
    try:
        req = urllib.request.Request(url, data=json.dumps({"text": message}).encode("utf-8"),
                                     method="POST", headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=15)
        print("[score][alert] sent: " + message)
    except Exception as exc:  # noqa: BLE001
        print(f"[score][alert] failed: {str(exc)[:150]}")


def _store_id_for(slug: str) -> str:
    """score の per_store キー(slug)を serving が使う store_id に変換する。
    相席屋は slug==store_id ("ay_*")、オリエンタルは短縮 slug に "ol_" を付与。
    """
    return slug if slug.startswith("ay_") else f"ol_{slug}"


# --------------------------------------------------------------------------- #
# プロダクト・スコアカード（純関数・ネットワーク無し）
#   A / v2 / baseline を同一スロットマッチングで、MAE 以外の実用指標でも採点する。
# --------------------------------------------------------------------------- #
PEAK_HIT_TOLERANCE_MIN = 30  # ピーク時刻の許容ズレ（<=30 分で hit）
PEAK_MIN_SLOTS = 20          # ピーク判定を有効化する最低マッチスロット数
PEAK_MIN_PEOPLE = 5.0        # 実測ピークがこれ未満の夜はピーク判定対象外
GHOST_LATE_START_HOUR = 23   # ゴースト判定の深夜帯開始（23:00〜翌05:00）
GHOST_LATE_END_HOUR = 5


def _peak_index(values: list[float | None]) -> int | None:
    best: float | None = None
    bi: int | None = None
    for i, v in enumerate(values):
        if v is None:
            continue
        if best is None or v > best:
            best = v
            bi = i
    return bi


def peak_time_hit30(
    times_min: list[int],
    actuals: list[float | None],
    preds: list[float | None],
    *,
    min_slots: int = PEAK_MIN_SLOTS,
    min_peak: float = PEAK_MIN_PEOPLE,
    tol_min: int = PEAK_HIT_TOLERANCE_MIN,
) -> bool | None:
    """予測ピークスロットが実測ピークスロットと <=tol_min 分か（店-夜ごとの bool）。

    有効条件: マッチスロットが min_slots 以上 かつ 実測ピークが min_peak 人以上。
    条件を満たさない夜は None（対象外）。times_min は各スロットの絶対分（同順配列）。
    """
    if len(actuals) < min_slots:
        return None
    a_i = _peak_index(actuals)
    if a_i is None or (actuals[a_i] or 0.0) < min_peak:
        return None
    p_i = _peak_index(preds)
    if p_i is None:
        return None
    return abs(times_min[p_i] - times_min[a_i]) <= tol_min


def ghost_index(
    actuals: list[float | None],
    preds: list[float | None],
    late_flags: list[bool],
) -> float | None:
    """深夜帯(23:00以降)で実測が実質ゼロのスロットでの平均予測総数（過剰予測=ゴースト）。

    「実質ゼロ」= 実測 <= max(1.0, その夜の実測ピークの5%)。対象スロットが無ければ None。
    """
    peak = max((a for a in actuals if a is not None), default=0.0)
    thr = max(1.0, 0.05 * peak)
    vals = [
        preds[i]
        for i in range(len(actuals))
        if late_flags[i]
        and actuals[i] is not None
        and actuals[i] <= thr
        and preds[i] is not None
    ]
    if not vals:
        return None
    return sum(vals) / len(vals)


def band_coverage(
    actuals: list[float | None],
    p10s: list[float | None],
    p90s: list[float | None],
) -> float | None:
    """p10 <= 実測 <= p90 を満たすマッチスロットの割合（v2 の帯の当たり率）。無ければ None。"""
    total = 0
    covered = 0
    for a, lo, hi in zip(actuals, p10s, p90s):
        if a is None or lo is None or hi is None:
            continue
        total += 1
        if lo <= a <= hi:
            covered += 1
    return (covered / total) if total else None


def _slot_min(dt: datetime) -> int:
    """スロット時刻を JST 15 分に丸め、ピーク距離計算用の絶対分（epoch 分）にする。"""
    j = dt.astimezone(JST)
    j = j.replace(minute=(j.minute // SLOT_MIN) * SLOT_MIN, second=0, microsecond=0)
    return int(j.timestamp() // 60)


def _is_late_slot(dt: datetime) -> bool:
    h = dt.astimezone(JST).hour
    return h >= GHOST_LATE_START_HOUR or h < GHOST_LATE_END_HOUR


def _mean_opt(values: list) -> float | None:
    nums = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    return round(sum(nums) / len(nums), 3) if nums else None


def _rate_opt(values: list) -> float | None:
    bools = [1.0 if v else 0.0 for v in values if v is not None]
    return round(sum(bools) / len(bools), 3) if bools else None


def _num_or_none(v: object) -> float | None:
    try:
        f = float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return None if (f != f or f in (float("inf"), float("-inf"))) else f


def _round_opt(v: float | None) -> float | None:
    return round(v, 3) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _fleet_scorecard(scorecard_per_store: dict[str, dict]) -> dict:
    """店別スコアカードを艦隊レベルに集計する（A/v2/baseline）。

    peak_hit30 は対象店の hit 率、ghost / band_coverage は対象店の平均。None（対象外）は除外。
    """
    def collect(pipeline: str, metric: str) -> list:
        return [
            sc[pipeline].get(metric)
            for sc in scorecard_per_store.values()
            if isinstance(sc.get(pipeline), dict)
        ]

    return {
        "a": {"peak_hit30": _rate_opt(collect("a", "peak_hit30")), "ghost": _mean_opt(collect("a", "ghost"))},
        "baseline": {
            "peak_hit30": _rate_opt(collect("baseline", "peak_hit30")),
            "ghost": _mean_opt(collect("baseline", "ghost")),
        },
        "v2": {
            "peak_hit30": _rate_opt(collect("v2", "peak_hit30")),
            "ghost": _mean_opt(collect("v2", "ghost")),
            "band_coverage": _mean_opt(collect("v2", "band_coverage")),
        },
    }


def blend_weight(ml_mae: float, baseline_mae: float, nights: int) -> float:
    """逆誤差ブレンド重み w_ml。

    w = baseline_mae / (ml_mae + baseline_mae) — ML が強い(誤差小)ほど 1 に、
    ベースラインが強いほど 0 に寄る。夜数が 4 未満のときは 0.5 へ収縮
    （w = (n*w + (4-n)*0.5)/4）し、最後に [0.15, 0.9] にクランプする。
    """
    try:
        ml = float(ml_mae)
        bl = float(baseline_mae)
    except (TypeError, ValueError):
        return 0.5
    denom = ml + bl
    w = (bl / denom) if denom > 0 else 0.5
    n = max(0, int(nights))
    if n < 4:
        w = (n * w + (4 - n) * 0.5) / 4
    return max(0.15, min(0.9, w))


def compute_blend_weights(
    bucket: str, supabase_url: str, key: str, night_dates: list[str]
) -> dict[str, float]:
    """直近最大7夜の本番スコア(accuracy/scores/<date>.json)を読み、店舗別に
    live_mae / live_baseline_mae を平均して逆誤差ブレンド重み {store_id: w_ml} を返す。

    ネットワーク I/O を伴うため、純粋な重み計算は blend_weight() に切り出してある
    （こちらは集計＋取得のオーケストレーション）。取得失敗した夜はスキップする。
    """
    agg: dict[str, dict[str, list[float]]] = {}
    for d in night_dates[:7]:
        raw = _storage_get(bucket, f"accuracy/scores/{d}.json", supabase_url, key)
        if raw is None:
            continue
        try:
            doc = json.loads(raw.decode())
        except Exception:  # noqa: BLE001
            continue
        per_store = doc.get("per_store") if isinstance(doc, dict) else None
        if not isinstance(per_store, dict):
            continue
        for slug, entry in per_store.items():
            if not isinstance(entry, dict):
                continue
            ml = entry.get("live_mae")
            bl = entry.get("live_baseline_mae")
            if not isinstance(ml, (int, float)) or not isinstance(bl, (int, float)):
                continue
            store_id = _store_id_for(slug)
            a = agg.setdefault(store_id, {"ml": [], "bl": []})
            a["ml"].append(float(ml))
            a["bl"].append(float(bl))

    weights: dict[str, float] = {}
    for store_id, a in agg.items():
        n = len(a["ml"])
        if n == 0:
            continue
        ml_mae = sum(a["ml"]) / n
        bl_mae = sum(a["bl"]) / n
        weights[store_id] = round(blend_weight(ml_mae, bl_mae, n), 4)
    return weights


def _write_step_summary(
    night_date: str,
    overall: float | None,
    overall_baseline: float | None,
    per_store: dict[str, dict],
    weights: dict[str, float],
    nights_used: int,
) -> None:
    """GITHUB_STEP_SUMMARY に艦隊 ML vs ベースライン、負け店一覧、ブレンド重み幅を書く。
    未設定(ローカル実行)や書き込み失敗時は何もしない。"""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    losing = [
        (s, v)
        for s, v in per_store.items()
        if isinstance(v.get("live_baseline_mae"), (int, float)) and v["live_mae"] > v["live_baseline_mae"]
    ]
    verdict = "✅ ML beating baseline"
    if overall is not None and overall_baseline is not None and overall > overall_baseline:
        verdict = "❌ ML LOSING to baseline"
    lines: list[str] = []
    lines.append(f"## Forecast accuracy — night {night_date}\n\n")
    lines.append(f"- Fleet live MAE: **{overall}** vs seasonal-naive baseline MAE: **{overall_baseline}**\n")
    lines.append(f"- Verdict: **{verdict}**\n")
    lines.append(f"- Stores losing to baseline: **{len(losing)}** / {len(per_store)}\n")
    if weights:
        ws = sorted(weights.values())
        lines.append(
            f"- Blend weights w_ml: min **{ws[0]:.2f}**, max **{ws[-1]:.2f}** "
            f"(stores={len(ws)}, nights_used={nights_used})\n"
        )
    else:
        lines.append("- Blend weights: (none computed yet)\n")
    if losing:
        lines.append("\n| store | live MAE | baseline MAE |\n|---|---|---|\n")
        for s, v in sorted(losing, key=lambda kv: kv[1]["live_mae"] - kv[1]["live_baseline_mae"], reverse=True)[:15]:
            lines.append(f"| {s} | {v['live_mae']} | {v['live_baseline_mae']} |\n")
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("".join(lines))
    except Exception as exc:  # noqa: BLE001
        print(f"[score] step summary write failed: {str(exc)[:120]}")


def _read_recent_scorecards(
    bucket: str, url: str, key: str, night_dates: list[str]
) -> dict[str, dict[str, list]]:
    """直近夜の scores/<date>.json から艦隊スコアカードを集めてローリング集計用に返す。"""
    acc: dict[str, dict[str, list]] = {
        "a": {"peak": [], "ghost": []},
        "v2": {"peak": [], "ghost": [], "cov": []},
        "baseline": {"peak": [], "ghost": []},
    }
    for d in night_dates[:7]:
        raw = _storage_get(bucket, f"accuracy/scores/{d}.json", url, key)
        if raw is None:
            continue
        try:
            doc = json.loads(raw.decode())
        except Exception:  # noqa: BLE001
            continue
        sc = doc.get("scorecard") if isinstance(doc, dict) else None
        if not isinstance(sc, dict):
            continue
        for pl in ("a", "v2", "baseline"):
            blk = sc.get(pl)
            if not isinstance(blk, dict):
                continue
            if isinstance(blk.get("peak_hit30"), (int, float)):
                acc[pl]["peak"].append(blk["peak_hit30"])
            if isinstance(blk.get("ghost"), (int, float)):
                acc[pl]["ghost"].append(blk["ghost"])
            if pl == "v2" and isinstance(blk.get("band_coverage"), (int, float)):
                acc["v2"]["cov"].append(blk["band_coverage"])
    return acc


def _write_scorecard_summary(
    night_date: str,
    overall: float | None,
    overall_v2: float | None,
    overall_baseline: float | None,
    fleet: dict,
    bucket: str,
    url: str,
    key: str,
    nights: list[dict],
) -> None:
    """GITHUB_STEP_SUMMARY に A vs v2 vs baseline の夜次スコアカード + 直近7夜ローリングを書く。

    未設定(ローカル実行)や失敗時は何もしない。v2 は shadow なので exit code には一切影響しない。
    """
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return

    def fmt(x: object) -> str:
        return "—" if x is None else str(x)

    a, v2, bl = fleet.get("a", {}), fleet.get("v2", {}), fleet.get("baseline", {})
    lines: list[str] = []
    lines.append(f"\n## Forecast v2 shadow scorecard — night {night_date}\n\n")
    lines.append("| metric | A (prod) | v2 (shadow) | baseline |\n|---|---|---|---|\n")
    lines.append(f"| MAE (lower=better) | {fmt(overall)} | {fmt(overall_v2)} | {fmt(overall_baseline)} |\n")
    lines.append(
        f"| peak_hit30 (higher=better) | {fmt(a.get('peak_hit30'))} | "
        f"{fmt(v2.get('peak_hit30'))} | {fmt(bl.get('peak_hit30'))} |\n"
    )
    lines.append(
        f"| ghost_index (lower=better) | {fmt(a.get('ghost'))} | "
        f"{fmt(v2.get('ghost'))} | {fmt(bl.get('ghost'))} |\n"
    )
    lines.append(f"| band_coverage (v2) | — | {fmt(v2.get('band_coverage'))} | — |\n")
    try:
        ra = _mean_opt([n.get("overall_live_mae") for n in nights[:7]])
        rv2 = _mean_opt([n.get("overall_v2_mae") for n in nights[:7]])
        rbl = _mean_opt([n.get("overall_baseline_mae") for n in nights[:7]])
        dates = [n.get("night_date") for n in nights if n.get("night_date")][:7]
        rsc = _read_recent_scorecards(bucket, url, key, dates)
        lines.append(f"\n### Rolling last-{len(dates)} nights\n\n")
        lines.append("| metric | A | v2 | baseline |\n|---|---|---|---|\n")
        lines.append(f"| MAE | {fmt(ra)} | {fmt(rv2)} | {fmt(rbl)} |\n")
        lines.append(
            f"| peak_hit30 | {fmt(_mean_opt(rsc['a']['peak']))} | "
            f"{fmt(_mean_opt(rsc['v2']['peak']))} | {fmt(_mean_opt(rsc['baseline']['peak']))} |\n"
        )
        lines.append(
            f"| ghost_index | {fmt(_mean_opt(rsc['a']['ghost']))} | "
            f"{fmt(_mean_opt(rsc['v2']['ghost']))} | {fmt(_mean_opt(rsc['baseline']['ghost']))} |\n"
        )
        lines.append(f"| band_coverage | — | {fmt(_mean_opt(rsc['v2']['cov']))} | — |\n")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"\n(rolling aggregation failed: {str(exc)[:100]})\n")
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("".join(lines))
    except Exception as exc:  # noqa: BLE001
        print(f"[score] scorecard summary write failed: {str(exc)[:120]}")


def main() -> int:
    _load_env()
    supabase_url = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_SERVICE_KEY") or ""
    bucket = (os.environ.get("FORECAST_MODEL_BUCKET") or "ml-models").strip()
    if not supabase_url or not key:
        raise SystemExit("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")

    # The night that just ended = yesterday (JST), since we run ~06:10 the next morning.
    night_date = (datetime.now(JST) - timedelta(days=1)).strftime("%Y%m%d")
    snap_raw = _storage_get(bucket, f"accuracy/snapshots/{night_date}.json", supabase_url, key)
    if snap_raw is None:
        # snapshot は毎晩 18:10 JST に走る前提なので、無いのは異常。サイレントに
        # green で終わらせず、監視が拾えるようアラート + 非ゼロ終了にする。
        msg = f"[MEGRIBI forecast accuracy] night {night_date}: no snapshot found — snapshot job may not have run."
        print(f"[score] no snapshot for {night_date} — nothing to score (snapshot job may not have run).")
        _alert(msg)
        return 1
    snapshot = json.loads(snap_raw.decode())
    by_slug = snapshot.get("by_slug") or {}
    expected = len(by_slug)

    base = datetime.strptime(night_date, "%Y%m%d").replace(tzinfo=JST)
    start = base.replace(hour=19, minute=0, second=0, microsecond=0)
    end = (start + timedelta(days=1)).replace(hour=5, minute=0, second=0, microsecond=0)
    start_iso = start.astimezone(timezone.utc).isoformat()
    end_iso = end.astimezone(timezone.utc).isoformat()

    # 7-days-earlier window for the LIVE seasonal-naive baseline ("same slot last week")
    start_prev_iso = (start - timedelta(days=7)).astimezone(timezone.utc).isoformat()
    end_prev_iso = (end - timedelta(days=7)).astimezone(timezone.utc).isoformat()

    # v2 SHADOW: snapshot_forecasts.py が同じ夜の JSON に併記した v2 予測（無ければ空）。
    v2_all = snapshot.get("v2") or {}

    per_store: dict[str, dict] = {}
    v2_per_store: dict[str, dict] = {}
    scorecard_per_store: dict[str, dict] = {}
    for slug, preds in by_slug.items():
        if not isinstance(preds, list) or not preds:
            continue
        # 相席屋は slug == store_id ("ay_*")。オリエンタルは短縮 slug なので "ol_" を付与。
        store_id = slug if slug.startswith("ay_") else f"ol_{slug}"
        slot_now = _slot_means(_fetch_actuals(supabase_url, key, store_id, start_iso, end_iso))
        slot_prev = _slot_means(_fetch_actuals(supabase_url, key, store_id, start_prev_iso, end_prev_iso))

        # --- A (本番、既存ロジックは不変) の MAE + A/baseline スコアカード用配列を収集 ---
        ml_err: list[float] = []
        base_err: list[float] = []
        a_times: list[int] = []
        a_actual: list[float | None] = []
        a_pred: list[float | None] = []
        a_late: list[bool] = []
        b_actual: list[float | None] = []
        b_pred: list[float | None] = []
        b_late: list[bool] = []
        for p in preds:
            dt = _parse_iso(p.get("ts", ""))
            if dt is None:
                continue
            actual = slot_now.get(_slot_key(dt))
            if actual is None:
                continue
            try:
                pred_total = float(p.get("total_pred") or 0.0)
            except (TypeError, ValueError):
                continue
            ml_err.append(abs(pred_total - actual))
            naive = slot_prev.get(_slot_key(dt - timedelta(days=7)))  # same clock slot, last week
            if naive is not None:
                base_err.append(abs(naive - actual))
            # スコアカード用（A と baseline は同一グリッド。baseline は naive のある slot のみ）。
            a_times.append(_slot_min(dt))
            a_actual.append(actual)
            a_pred.append(pred_total)
            a_late.append(_is_late_slot(dt))
            b_actual.append(actual if naive is not None else None)
            b_pred.append(naive)
            b_late.append(_is_late_slot(dt))
        if ml_err:
            entry = {"live_mae": round(sum(ml_err) / len(ml_err), 2), "matched_slots": len(ml_err)}
            if base_err:
                b = sum(base_err) / len(base_err)
                entry["live_baseline_mae"] = round(b, 2)
                if b > 0:
                    # >0 means ML beats "same slot last week" in production; <=0 means it does not
                    entry["ml_vs_baseline_live_pct"] = round((b - entry["live_mae"]) / b * 100.0, 1)
            per_store[slug] = entry

        # --- v2 (shadow) の MAE + 帯カバレッジ + スコアカード用配列 ---
        v2_entry = v2_all.get(slug)
        v2_times: list[int] = []
        v2_actual: list[float | None] = []
        v2_pred: list[float | None] = []
        v2_late: list[bool] = []
        v2_p10: list[float | None] = []
        v2_p90: list[float | None] = []
        v2_err: list[float] = []
        if isinstance(v2_entry, dict) and isinstance(v2_entry.get("data"), list):
            for p in v2_entry["data"]:
                if not isinstance(p, dict):
                    continue
                dt = _parse_iso(p.get("ts", ""))
                if dt is None:
                    continue
                actual = slot_now.get(_slot_key(dt))
                if actual is None:
                    continue
                try:
                    pt = float(p.get("total_pred") or 0.0)
                except (TypeError, ValueError):
                    continue
                v2_err.append(abs(pt - actual))
                v2_times.append(_slot_min(dt))
                v2_actual.append(actual)
                v2_pred.append(pt)
                v2_late.append(_is_late_slot(dt))
                v2_p10.append(_num_or_none(p.get("p10")))
                v2_p90.append(_num_or_none(p.get("p90")))
            if v2_err:
                v2e: dict = {
                    "v2_mae": round(sum(v2_err) / len(v2_err), 2),
                    "matched_slots": len(v2_err),
                    "night_type": v2_entry.get("night_type"),
                    "special_block": v2_entry.get("special_block"),
                    "fallback": v2_entry.get("template_fallback"),
                    # v2.1 観測性: この夜の v2 スケールが blend50 か scale_ref か（snapshot 由来）。
                    "scale_source": v2_entry.get("scale_source"),
                }
                cov = band_coverage(v2_actual, v2_p10, v2_p90)
                if cov is not None:
                    v2e["band_coverage"] = round(cov, 3)
                v2_per_store[slug] = v2e

        # --- 店別スコアカード（A / v2 / baseline を同一マッチングで） ---
        if ml_err:
            sc: dict = {
                "a": {
                    "peak_hit30": peak_time_hit30(a_times, a_actual, a_pred),
                    "ghost": _round_opt(ghost_index(a_actual, a_pred, a_late)),
                },
                "baseline": {
                    "peak_hit30": peak_time_hit30(a_times, a_actual, b_pred),
                    "ghost": _round_opt(ghost_index(b_actual, b_pred, b_late)),
                },
            }
            if v2_times:
                sc["v2"] = {
                    "peak_hit30": peak_time_hit30(v2_times, v2_actual, v2_pred),
                    "ghost": _round_opt(ghost_index(v2_actual, v2_pred, v2_late)),
                    "band_coverage": _round_opt(band_coverage(v2_actual, v2_p10, v2_p90)),
                }
            scorecard_per_store[slug] = sc

    maes = [v["live_mae"] for v in per_store.values()]
    overall = round(sum(maes) / len(maes), 2) if maes else None
    base_maes = [v["live_baseline_mae"] for v in per_store.values() if "live_baseline_mae" in v]
    overall_baseline = round(sum(base_maes) / len(base_maes), 2) if base_maes else None
    v2_maes = [v["v2_mae"] for v in v2_per_store.values() if "v2_mae" in v]
    overall_v2 = round(sum(v2_maes) / len(v2_maes), 2) if v2_maes else None
    fleet_scorecard = _fleet_scorecard(scorecard_per_store)
    result = {
        "night_date": night_date,
        "scored_at_utc": datetime.now(timezone.utc).isoformat(),
        "overall_live_mae": overall,
        "overall_baseline_mae": overall_baseline,
        "stores_scored": len(per_store),
        "per_store": per_store,
        # --- 追加(後方互換): v2 と scorecard を別キーで併記。既存 consumer は無視できる。 ---
        "v2": {
            "overall_v2_mae": overall_v2,
            "overall_baseline_mae": overall_baseline,
            "stores_scored": len(v2_per_store),
            "per_store": v2_per_store,
        },
        "scorecard": {**fleet_scorecard, "per_store": scorecard_per_store},
    }
    _storage_put(bucket, f"accuracy/scores/{night_date}.json", json.dumps(result, ensure_ascii=False).encode("utf-8"), supabase_url, key)

    # rolling summary (newest first, capped)
    summary = {"nights": []}
    existing = _storage_get(bucket, "accuracy/scores/summary.json", supabase_url, key)
    if existing is not None:
        try:
            loaded = json.loads(existing.decode())
            if isinstance(loaded, dict) and isinstance(loaded.get("nights"), list):
                summary = loaded
        except Exception:  # noqa: BLE001
            pass
    summary["nights"] = (
        [{"night_date": night_date, "overall_live_mae": overall,
          "overall_baseline_mae": overall_baseline, "stores_scored": len(per_store),
          # 追加(後方互換): v2 の夜次 MAE。_fetch_live_accuracy は無視する（既存キーは不変）。
          "overall_v2_mae": overall_v2}]
        + [n for n in summary["nights"] if n.get("night_date") != night_date]
    )[:SUMMARY_KEEP]
    summary["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
    _storage_put(bucket, "accuracy/scores/summary.json", json.dumps(summary, ensure_ascii=False).encode("utf-8"), supabase_url, key)

    # --- closed-loop feedback: 直近最大7夜の本番スコアから店舗別ブレンド重みを算出し、
    # serving が取り込む accuracy/blend_weights.json を更新する（本丸③）。
    weights: dict[str, float] = {}
    try:
        recent_dates = [n.get("night_date") for n in summary["nights"] if n.get("night_date")][:7]
        weights = compute_blend_weights(bucket, supabase_url, key, recent_dates)
        weights_payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "nights_used": len(recent_dates),
            "weights": weights,
        }
        _storage_put(
            bucket, "accuracy/blend_weights.json",
            json.dumps(weights_payload, ensure_ascii=False).encode("utf-8"), supabase_url, key,
        )
        if weights:
            ws = sorted(weights.values())
            print(f"[score] blend_weights: {len(weights)} stores, w_ml {ws[0]:.2f}..{ws[-1]:.2f} (nights_used={len(recent_dates)})")
        else:
            print("[score] blend_weights: no per-store scores yet (wrote empty weights)")
    except Exception as exc:  # noqa: BLE001 — 重み算出失敗は scoring 本体を落とさない
        print(f"[score] blend_weights compute failed: {str(exc)[:150]}")

    # --- Act (close the PDCA loop): alert on production degradation ---
    alerts: list[str] = []
    if overall is not None and overall_baseline is not None and overall > overall_baseline:
        alerts.append(f"ML is NOT beating the naive baseline in production (live MAE {overall} vs naive {overall_baseline}).")
    recent = [n.get("overall_live_mae") for n in summary["nights"][1:8]
              if isinstance(n.get("overall_live_mae"), (int, float))]
    if overall is not None and recent:
        med = sorted(recent)[len(recent) // 2]
        if med > 0 and overall > med * 1.5:
            alerts.append(f"Live forecast error spiked: tonight {overall} vs recent median {round(med, 2)} (>1.5x).")

    # スナップショットされていた店舗数(expected)に対し、実際に答え合わせできた
    # 店舗数(stores_scored)が 90% 未満なら異常。0 件を含め、監視ジョブが
    # green のまま死ぬのを防ぐ。expected==0（スナップショット自体が空）は
    # 別枠でログのみ（snapshot 側の問題なので score 側の非ゼロ終了はしない）。
    stores_scored = len(per_store)
    coverage_failure = expected > 0 and stores_scored < expected * 0.9
    if coverage_failure:
        alerts.append(
            f"Only {stores_scored}/{expected} stores were scored (<90% coverage) — "
            "check logs collection / store id mapping."
        )

    if alerts:
        worst = sorted(per_store.items(), key=lambda kv: kv[1]["live_mae"], reverse=True)[:5]
        worst_str = ", ".join(f"{s}={v['live_mae']}" for s, v in worst)
        _alert(f"[MEGRIBI forecast accuracy] night {night_date}: " + " ".join(alerts) + f" Worst stores: {worst_str}")

    print(f"[score] night={night_date} overall_live_mae={overall} baseline={overall_baseline} stores_scored={stores_scored}/{expected}")
    for slug in sorted(per_store, key=lambda s: per_store[s]["live_mae"], reverse=True):
        v = per_store[slug]
        print(f"  {slug:<16} live_mae={v['live_mae']:>6}  slots={v['matched_slots']}")
    if not per_store:
        print("[score] no stores could be scored (no overlapping actual slots).")

    print(f"[score] v2(shadow) overall_v2_mae={overall_v2} stores_v2={len(v2_per_store)} "
          f"scorecard={json.dumps(fleet_scorecard, ensure_ascii=True)}")

    # GitHub Actions のジョブ画面に艦隊サマリを表示（PDCAの可視化）。
    _write_step_summary(night_date, overall, overall_baseline, per_store, weights, len(summary["nights"][:7]))
    # 追加: A vs v2 vs baseline の夜次スコアカード + 直近7夜のローリング集計。
    _write_scorecard_summary(
        night_date, overall, overall_v2, overall_baseline, fleet_scorecard,
        bucket, supabase_url, key, summary["nights"],
    )

    # 艦隊 ML がナイーブ・ベースラインに負けた夜はジョブを RED にして notify-on-failure を
    # 発火させる（Act 断線の修理）。ACCURACY_FAIL_ON_BASELINE_LOSS=0 で無効化可。
    baseline_loss = (
        overall is not None and overall_baseline is not None and overall > overall_baseline
    )
    fail_on_loss = os.environ.get("ACCURACY_FAIL_ON_BASELINE_LOSS", "1").strip() == "1"

    if coverage_failure:
        return 1
    if baseline_loss and fail_on_loss:
        print(f"[score] FAIL: fleet ML lost to baseline (live {overall} > baseline {overall_baseline}). "
              "Set ACCURACY_FAIL_ON_BASELINE_LOSS=0 to silence.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
