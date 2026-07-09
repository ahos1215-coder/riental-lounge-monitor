"""ML 予測の後処理: 季節ナイーブ・ベースラインとのブレンド + 深夜帯クランプ。

本番の答え合わせ（scripts/score_forecasts.py）で判明した2つの問題を serving 側で塞ぐ、
closed-loop 精度改善の実装：

1. 深夜帯クランプ (late_night_clamp)
   客が帰った後（実測がピークの2割未満）も ML が「まだ人がいる」と予測し続ける
   overshoot が深夜帯（23時以降）で顕著。店舗“自身”の直近同一スロット実測の
   max×HEADROOM を上限に各スロットを抑える。gangnam のように毎晩 00:30 以降ほぼ0の
   店舗では上限がほぼ0に潰れ、過大予測が消える。実測が本当に賑わう店舗は上限が高いので
   無傷。

   曜日バケット対応 (FORECAST_CLAMP_DOW_AWARE, 既定 ON):
   8日間の直近ウィンドウには必ず金・土が含まれるため、相席屋系のように「平日深夜は
   閉店・週末深夜は賑わう」店舗では、全日結合の上限が週末の実測に引っ張られて底上げ
   され、平日深夜のクランプが実質無効化されるバグがあった（例: weekday 02:00 実測は
   常に0なのに、週末の実測込みの上限が33.8まで残り、ML=25 が無傷で通過）。
   これを塞ぐため、同一スロットの統計を「平日夜」「週末夜」バケットに分けて集計し、
   予測スロットも同じ夜セッション判定でバケット分けして対応する側の上限だけを見る。
   深夜0-5時台は前夜19-24時台の続きの夜セッションとみなし、-6時間シフトしてから
   曜日判定する（金・土発の夜 → weekend、それ以外 → weekday）。
   バケットの実測夜数が閾値未満（平日3・週末2）なら、そのバケットは信頼できないので
   従来通りの全日結合の上限にフォールバックする（＝今日より弱くなることは無い）。

2. ベースライン・ブレンド (blend_with_baseline)
   pred = w_ml*ML + (1-w_ml)*季節ナイーブ（同一店の7日前・同一スロット実測）。
   重み w_ml は score_forecasts.py が本番スコアから逆誤差で算出し blend_weights.json に
   書き出したものを serving が取り込む。ML が強い店（勝ち店）は w_ml≈0.9 でほぼ無変化、
   ML が負けている店は w_ml≈0.2 でほぼベースラインに寄る。

適用順序: ブレンド → クランプ（クランプが最終出力を上限で締める）。

すべて純粋関数（ネットワーク無し）でユニットテスト可能。何が起きても予測を壊さないよう、
入力不足・例外時は入力をそのまま返す“無害な no-op”を徹底する。ただし無音の no-op は
本番での実障害を見えなくするため、例外発生時は必ず警告ログを残してから入力を返す。
"""

from __future__ import annotations

import logging
import os
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# 深夜帯クランプを適用する開始時刻(JST)。夜セッションは 19:00-05:00 に跨るため、
# 「23時以降」= 時刻 >= 23 または 時刻 < 5（日跨ぎ後の未明）を深夜帯とみなす。
LATE_CLAMP_START_HOUR = 23
LATE_CLAMP_END_HOUR = 5
# 同一スロットで実測のある夜がこれ未満なら履歴が薄すぎるのでクランプしない
# (全日結合・レガシー/フォールバック用の閾値)。
CLAMP_MIN_NIGHTS = 3
# 曜日バケット版の閾値。週末(金・土発の夜)は8日ウィンドウでも出現数が少ないため、
# 平日より緩い閾値にする。
CLAMP_MIN_NIGHTS_WEEKDAY = 3
CLAMP_MIN_NIGHTS_WEEKEND = 2
# 深夜0-5時台のスロットを「前夜のセッションの続き」とみなすための逆シフト時間。
NIGHT_SESSION_SHIFT_HOURS = 6
# pandas の Timestamp.weekday(): 月=0, 火=1, 水=2, 木=3, 金=4, 土=5, 日=6。
WEEKEND_SESSION_WEEKDAYS = {4, 5}  # 金・土発の夜 -> "weekend" バケット


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not (isinstance(v, float) and (np.isnan(v) or np.isinf(v)))


def _as_ts(value: Any, tz: str) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize(tz)
    return ts.tz_convert(tz)


def _is_late_night(ts: pd.Timestamp) -> bool:
    """夜セッション(19:00-05:00)のうち「23時以降」の深夜帯か。"""
    h = int(ts.hour)
    return h >= LATE_CLAMP_START_HOUR or h < LATE_CLAMP_END_HOUR


def _night_session_shift(ts: pd.Timestamp) -> pd.Timestamp:
    """深夜0-5時台のスロットを「前夜のセッションの続き」として扱うための -6h シフト。"""
    return ts - pd.Timedelta(hours=NIGHT_SESSION_SHIFT_HOURS)


def _night_bucket(ts: pd.Timestamp) -> str:
    """スロット時刻が属する「夜セッション」を weekday/weekend バケットに分類する。

    深夜0-5時台のスロットは前夜19-24時台の続きなので、シフトせずそのまま曜日判定すると
    「土曜02:00」が日曜扱いに、「月曜02:00」が月曜自身のまま…という誤判定になる
    （前者は本来「金曜の夜」の続き、後者は「日曜の夜」の続き）。-6時間シフトしてから
    曜日を見ることで、どのスロット時刻でも「その夜が始まった曜日」に正しく丸められる。
    金(4)・土(5)発の夜 → "weekend"、それ以外 → "weekday"。

    例: 土02:00-6h=金20:00→weekend / 火02:00-6h=月20:00→weekday /
        日02:00-6h=土20:00→weekend / 月02:00-6h=日20:00→weekday /
        金23:30-6h=金17:30→weekend
    """
    shifted = _night_session_shift(ts)
    return "weekend" if int(shifted.weekday()) in WEEKEND_SESSION_WEEKDAYS else "weekday"


def same_slot_stats(history_df: pd.DataFrame | None, freq_min: int) -> dict[tuple[int, int], tuple[float, int]]:
    """履歴の実測から {(hour, minute): (max_total, n_nights)} を作る（全日結合・レガシー版）。

    minute は freq_min スロットに floor 済み。n_nights は「その時刻スロットに実測行が
    存在したカレンダー日数」= その店がそのスロットで観測された夜の数。
    曜日を区別しないため、週末の実測が平日の上限を底上げしうる（→ same_slot_stats_by_bucket
    が曜日バケット版。この関数はそのフォールバック用途とレガシー互換のために残す）。
    """
    if history_df is None or getattr(history_df, "empty", True):
        return {}
    if "ts" not in history_df.columns or "total" not in history_df.columns:
        return {}
    freq = max(1, int(freq_min))
    try:
        ts = pd.to_datetime(history_df["ts"])
        total = pd.to_numeric(history_df["total"], errors="coerce")
        frame = pd.DataFrame(
            {
                "hour": ts.dt.hour.to_numpy(),
                "minute": ((ts.dt.minute // freq) * freq).to_numpy(),
                "date": ts.dt.date.to_numpy(),
                "total": total.to_numpy(),
            }
        ).dropna(subset=["total"])
    except Exception as exc:  # noqa: BLE001 — 後処理は予測を壊さない(要監視のため警告ログ)
        logger.warning("postprocess.same_slot_stats failed, skipping clamp stats: %s", exc)
        return {}
    if frame.empty:
        return {}
    stats: dict[tuple[int, int], tuple[float, int]] = {}
    for (h, m), grp in frame.groupby(["hour", "minute"]):
        stats[(int(h), int(m))] = (float(grp["total"].max()), int(grp["date"].nunique()))
    return stats


def same_slot_stats_by_bucket(
    history_df: pd.DataFrame | None, freq_min: int
) -> dict[tuple[str, int, int], tuple[float, int]]:
    """same_slot_stats の曜日バケット版: {(bucket, hour, minute): (max_total, n_nights)}。

    bucket は "weekday" / "weekend"（_night_bucket 参照、深夜0-5時台は -6h シフトして
    前夜のセッションとして分類）。n_nights は同一バケット内でそのスロットに実測行が
    あった「夜セッション」の数（session_date = シフト後の日付でユニーク化するため、
    深夜0-5時台の行も前夜1夜として正しく数えられる）。
    """
    if history_df is None or getattr(history_df, "empty", True):
        return {}
    if "ts" not in history_df.columns or "total" not in history_df.columns:
        return {}
    freq = max(1, int(freq_min))
    try:
        ts = pd.to_datetime(history_df["ts"])
        total = pd.to_numeric(history_df["total"], errors="coerce")
        shifted = ts - pd.Timedelta(hours=NIGHT_SESSION_SHIFT_HOURS)
        bucket = np.where(shifted.dt.weekday.isin(WEEKEND_SESSION_WEEKDAYS), "weekend", "weekday")
        frame = pd.DataFrame(
            {
                "bucket": bucket,
                "hour": ts.dt.hour.to_numpy(),
                "minute": ((ts.dt.minute // freq) * freq).to_numpy(),
                "session_date": shifted.dt.date.to_numpy(),
                "total": total.to_numpy(),
            }
        ).dropna(subset=["total"])
    except Exception as exc:  # noqa: BLE001 — 後処理は予測を壊さない(要監視のため警告ログ)
        logger.warning("postprocess.same_slot_stats_by_bucket failed, skipping bucket stats: %s", exc)
        return {}
    if frame.empty:
        return {}
    stats: dict[tuple[str, int, int], tuple[float, int]] = {}
    for (b, h, m), grp in frame.groupby(["bucket", "hour", "minute"]):
        stats[(str(b), int(h), int(m))] = (
            float(grp["total"].max()),
            int(grp["session_date"].nunique()),
        )
    return stats


def actual_slot_map(history_df: pd.DataFrame | None, tz: str, freq_min: int) -> dict[pd.Timestamp, dict[str, float | None]]:
    """{floor 済みスロット時刻: {"total","men","women"}} を履歴の実測から作る。

    同一スロットに複数行（5分粒度など）がある場合は平均。季節ナイーブ・ベースライン
    （7日前の同一スロット実測）の参照に使う。
    """
    if history_df is None or getattr(history_df, "empty", True):
        return {}
    if "ts" not in history_df.columns or "total" not in history_df.columns:
        return {}
    freq = f"{max(1, int(freq_min))}min"
    try:
        ts = pd.to_datetime(history_df["ts"])
        floored = ts.dt.floor(freq)
        if "men" in history_df.columns:
            men = pd.to_numeric(history_df["men"], errors="coerce")
        else:
            men = pd.Series(np.nan, index=history_df.index)
        if "women" in history_df.columns:
            women = pd.to_numeric(history_df["women"], errors="coerce")
        else:
            women = pd.Series(np.nan, index=history_df.index)
        frame = pd.DataFrame(
            {
                "slot": floored.to_numpy(),
                "total": pd.to_numeric(history_df["total"], errors="coerce").to_numpy(),
                "men": men.to_numpy(),
                "women": women.to_numpy(),
            }
        )
        grouped = frame.groupby("slot").mean(numeric_only=True)
    except Exception as exc:  # noqa: BLE001 — 後処理は予測を壊さない(要監視のため警告ログ)
        logger.warning("postprocess.actual_slot_map failed, skipping baseline map: %s", exc)
        return {}
    out: dict[pd.Timestamp, dict[str, float | None]] = {}
    for slot, row in grouped.iterrows():
        out[pd.Timestamp(slot)] = {
            "total": float(row["total"]) if pd.notna(row.get("total")) else None,
            "men": float(row["men"]) if pd.notna(row.get("men")) else None,
            "women": float(row["women"]) if pd.notna(row.get("women")) else None,
        }
    return out


def blend_with_baseline(
    points: list[dict],
    history_df: pd.DataFrame | None,
    tz: str,
    *,
    w_ml: float,
    freq_min: int = 15,
) -> tuple[list[dict], int]:
    """各スロットを pred = w_ml*ML + (1-w_ml)*季節ナイーブ・ベースラインでブレンドする。

    ベースライン = 同一店の「7日前・同一スロット」の実測。その夜の該当スロットが
    履歴に無ければそのスロットはブレンドせず ML のまま（skip）。men/women を各々ブレンドし、
    total = men + women で内部整合を保つ（後段クランプのスケール整合のため）。

    - w_ml >= 1.0 なら純 ML（no-op）。FORECAST_BASELINE_BLEND=0 で全体を無効化。
    - 返り値: (points, blended_slots) — blended_slots は実際にブレンドが効いた件数。
    - 想定外の例外が起きた場合は警告ログを残し、points をそのまま返す（no-op だが無音にはしない）。
    """
    if not points:
        return points, 0
    if os.getenv("FORECAST_BASELINE_BLEND", "1").strip() != "1":
        return points, 0
    try:
        try:
            w = float(w_ml)
        except (TypeError, ValueError):
            w = 1.0
        if not np.isfinite(w) or w >= 1.0:
            return points, 0
        w = max(0.0, min(1.0, w))

        slot_map = actual_slot_map(history_df, tz, freq_min)
        if not slot_map:
            return points, 0
        freq = f"{max(1, int(freq_min))}min"

        out: list[dict] = []
        blended = 0
        for p in points:
            q = dict(p)
            mp, wp = p.get("men_pred"), p.get("women_pred")
            if not _is_num(mp) or not _is_num(wp):
                out.append(q)
                continue
            try:
                ts = _as_ts(p["ts"], tz)
                base_slot = (ts - pd.Timedelta(days=7)).floor(freq)
            except Exception:  # noqa: BLE001 — 個々のスロットのts不正はスキップ
                out.append(q)
                continue
            base = slot_map.get(base_slot)
            if base is None:
                out.append(q)
                continue
            base_men, base_women = base.get("men"), base.get("women")
            if not _is_num(base_men) or not _is_num(base_women):
                # gendered ベースラインが無い場合は、総数を ML の男女比で割って使う。
                base_total = base.get("total")
                if not _is_num(base_total):
                    out.append(q)
                    continue
                denom = float(mp) + float(wp)
                male_frac = (float(mp) / denom) if denom > 0 else 0.5
                base_men = float(base_total) * male_frac
                base_women = float(base_total) * (1.0 - male_frac)

            new_men = max(w * float(mp) + (1.0 - w) * float(base_men), 0.0)
            new_women = max(w * float(wp) + (1.0 - w) * float(base_women), 0.0)
            q["men_pred"] = new_men
            q["women_pred"] = new_women
            q["total_pred"] = new_men + new_women
            q["blend_w_ml"] = round(w, 3)
            blended += 1
            out.append(q)
        return out, blended
    except Exception as exc:  # noqa: BLE001 — 後処理は予測を壊さない(要監視のため警告ログ)
        logger.warning("postprocess.blend_with_baseline failed, returning input unchanged: %s", exc)
        return points, 0


def late_night_clamp(
    points: list[dict],
    history_df: pd.DataFrame | None,
    tz: str,
    *,
    freq_min: int = 15,
) -> tuple[list[dict], int]:
    """23:00 JST 以降の各予測スロットを、店舗自身の直近同一スロット実測で上限クランプする。

    cap = HEADROOM × max(直近ウィンドウでその15分スロットに観測された実測 total)
      - HEADROOM = FORECAST_LATE_CLAMP_HEADROOM（既定 1.3）
      - 23:00 より前（19-22時台）・未明以外のスロットは一切触らない
      - total を上限まで縮小した場合、men/women も同じ比率で縮小（内部整合）

    曜日バケット対応 (FORECAST_CLAMP_DOW_AWARE, 既定 "1"=ON):
      - 予測スロット・履歴行それぞれを _night_bucket() で "weekday"/"weekend" に分類
        （深夜0-5時台は -6h シフトして前夜のセッションとして判定）。
      - 対応するバケットの統計（same_slot_stats_by_bucket）を優先して使う。
        バケット内の実測夜数が閾値（weekday>=3, weekend>=2）を満たす場合のみ採用。
      - 閾値未満、または FORECAST_CLAMP_DOW_AWARE=0 の場合は、従来通り全日結合の統計
        （same_slot_stats, CLAMP_MIN_NIGHTS=3）にフォールバックする。これにより
        新ロジックが今までより「弱く」なることは無い（同じかそれ以上に厳密になるだけ）。
      - クランプが効いた場合、どちらの統計を使ったかを clamp_bucket
        ("weekday"/"weekend"/"all_days") として点ごとに残す（観測性のため）。

    - FORECAST_LATE_CLAMP=0 で無効化。
    - 返り値: (points, clamped_slots) — clamped_slots は実際に上限が効いた件数。
      各 point には clamped=True / clamp_cap / clamp_bucket を付与し観測可能にする。
    - 想定外の例外が起きた場合は警告ログを残し、points をそのまま返す（no-op だが無音にはしない）。
    """
    if not points:
        return points, 0
    if os.getenv("FORECAST_LATE_CLAMP", "1").strip() != "1":
        return points, 0
    try:
        headroom = _env_float("FORECAST_LATE_CLAMP_HEADROOM", 1.3)
        if headroom < 0:
            headroom = 1.3
        dow_aware = os.getenv("FORECAST_CLAMP_DOW_AWARE", "1").strip() == "1"

        legacy_stats = same_slot_stats(history_df, freq_min)
        bucket_stats = same_slot_stats_by_bucket(history_df, freq_min) if dow_aware else {}
        if not legacy_stats and not bucket_stats:
            return points, 0
        freq = max(1, int(freq_min))

        out: list[dict] = []
        clamped = 0
        for p in points:
            q = dict(p)
            total = p.get("total_pred")
            if not _is_num(total):
                out.append(q)
                continue
            try:
                ts = _as_ts(p["ts"], tz)
            except Exception:  # noqa: BLE001 — 個々のスロットのts不正はスキップ
                out.append(q)
                continue
            if not _is_late_night(ts):
                out.append(q)
                continue
            hour = int(ts.hour)
            minute = (int(ts.minute) // freq) * freq

            cap: float | None = None
            clamp_bucket: str | None = None
            if dow_aware:
                bucket = _night_bucket(ts)
                bstat = bucket_stats.get((bucket, hour, minute))
                min_nights = (
                    CLAMP_MIN_NIGHTS_WEEKEND if bucket == "weekend" else CLAMP_MIN_NIGHTS_WEEKDAY
                )
                if bstat is not None and bstat[1] >= min_nights:
                    cap = headroom * bstat[0]
                    clamp_bucket = bucket

            if cap is None:
                # バケット統計が使えない(閾値未満 or dow_aware無効) -> 全日結合にフォールバック。
                lstat = legacy_stats.get((hour, minute))
                if lstat is None or lstat[1] < CLAMP_MIN_NIGHTS:
                    out.append(q)
                    continue
                cap = headroom * lstat[0]
                clamp_bucket = "all_days"

            total_f = float(total)
            if total_f > cap:
                scale = (cap / total_f) if total_f > 0 else 0.0
                q["total_pred"] = cap
                for g in ("men_pred", "women_pred"):
                    v = p.get(g)
                    if _is_num(v):
                        q[g] = float(v) * scale
                q["clamped"] = True
                q["clamp_cap"] = round(cap, 3)
                q["clamp_bucket"] = clamp_bucket
                clamped += 1
            out.append(q)
        return out, clamped
    except Exception as exc:  # noqa: BLE001 — 後処理は予測を壊さない(要監視のため警告ログ)
        logger.warning("postprocess.late_night_clamp failed, returning input unchanged: %s", exc)
        return points, 0
