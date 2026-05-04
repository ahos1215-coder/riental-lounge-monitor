from __future__ import annotations

"""
週次 Good Window JSON 生成。閾値・運用の調整は plan/WEEKLY_INSIGHTS_TUNING.md を参照。

v2 (2026-05): 4 Phase 改善
- Phase A: metric_interpretations (数値の意味付け、e.g. "1日平均 142 件")
- Phase B: day_hour_heatmap (曜日 × 時間帯の混雑ヒートマップ)
- Phase C: ai_commentary (Gemini 2.5 Flash による自然文解説)
- Phase D: next_week_recommendations (来週の狙い目時間 TOP 3)
"""

import argparse
import importlib.util
import inspect
import json
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
MEGRIBI_SCORE_PATH = REPO_ROOT / "oriental" / "ml" / "megribi_score.py"

if not MEGRIBI_SCORE_PATH.exists():
    raise SystemExit(f"megribi_score not found: {MEGRIBI_SCORE_PATH}")

spec = importlib.util.spec_from_file_location("megribi_score", MEGRIBI_SCORE_PATH)
if spec is None or spec.loader is None:
    raise SystemExit("failed to load megribi_score module")

megribi_score_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(megribi_score_module)

find_good_windows = megribi_score_module.find_good_windows


DEFAULT_BASE_URL = "https://www.meguribi.jp"
DEFAULT_LIMIT = 5000
DEFAULT_SCORE_THRESHOLD = 0.40
DEFAULT_MIN_DURATION_MINUTES = 60
DEFAULT_IDEAL = 0.7
DEFAULT_GENDER_WEIGHT = 1.5
DEFAULT_HTTP_TIMEOUT_SECONDS = 60
DEFAULT_HTTP_RETRIES = 3
DEFAULT_USER_AGENT = "MEGRIBI-weekly-insights-bot"


def _pick_value(row: dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        if key in row:
            return row[key]
    return None


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_timestamp(row: dict[str, Any]) -> datetime | None:
    raw = _pick_value(row, ("timestamp", "ts", "t", "observed_at", "observedAt", "created_at", "createdAt"))
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        value = float(raw)
        if value > 1e12:
            value /= 1000.0
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed
    return None


def _percentile(values: list[float], percent: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (len(sorted_values) - 1) * (percent / 100.0)
    lower = int(rank)
    upper = min(lower + 1, len(sorted_values) - 1)
    if lower == upper:
        return sorted_values[lower]
    weight = rank - lower
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * weight


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _load_rows(
    base_url: str,
    store: str,
    limit: int,
    *,
    timeout_seconds: int,
    retries: int,
    user_agent: str,
) -> list[dict[str, Any]]:
    query = urlencode({"store": store, "limit": str(limit)})
    url = f"{base_url.rstrip('/')}/api/range?{query}"
    headers = {"accept": "application/json", "User-Agent": user_agent}
    last_error: Exception | None = None

    for attempt in range(1, retries + 1):
        try:
            req = Request(url, headers=headers)
            with urlopen(req, timeout=timeout_seconds) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            if isinstance(payload, list):
                return payload
            if isinstance(payload, dict):
                rows = payload.get("rows")
                if isinstance(rows, list):
                    return rows
            return []
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            print(
                f"[weekly-insights] fetch failed attempt {attempt}/{retries}: {exc}",
                file=sys.stderr,
            )
            if attempt < retries:
                sleep_seconds = min(2 ** (attempt - 1), 10)
                print(
                    f"[weekly-insights] retrying in {sleep_seconds}s",
                    file=sys.stderr,
                )
                time.sleep(sleep_seconds)

    if last_error is not None:
        raise last_error
    raise RuntimeError("weekly insights fetch failed")


def _collect_totals(rows: list[dict[str, Any]]) -> list[float]:
    totals: list[float] = []
    for row in rows:
        total = _to_float(_pick_value(row, ("total", "sum")))
        if total is None:
            men = _to_float(_pick_value(row, ("men", "male", "m")))
            women = _to_float(_pick_value(row, ("women", "female", "f")))
            if men is None or women is None:
                continue
            total = men + women
        if total is None:
            continue
        totals.append(total)
    return totals


def _build_points(rows: list[dict[str, Any]], baseline: float) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for row in rows:
        dt = _parse_timestamp(row)
        if dt is None:
            continue
        men = _to_float(_pick_value(row, ("men", "male", "m")))
        women = _to_float(_pick_value(row, ("women", "female", "f")))
        if men is None or women is None:
            continue
        denom = men + women
        if denom <= 0:
            continue
        female_ratio = women / denom
        total = _to_float(_pick_value(row, ("total", "sum")))
        if total is None:
            total = denom
        if baseline > 0:
            occupancy_rate = min(1.0, total / baseline)
        else:
            occupancy_rate = 0.0
        points.append(
            {
                "timestamp": dt,
                "female_ratio": female_ratio,
                "occupancy_rate": occupancy_rate,
                "stability": 1.0,
            }
        )
    return points


def _series_compact_points(points: list[dict[str, Any]], max_n: int = 240) -> list[dict[str, Any]]:
    """時系列チャート用にサンプルを間引く（JSON サイズと描画コストのバランス）。"""
    if not points:
        return []
    sorted_pts = sorted(points, key=lambda p: p.get("timestamp"))
    n = len(sorted_pts)
    if n <= max_n:
        idxs = list(range(n))
    else:
        step = (n - 1) / (max_n - 1)
        idxs = sorted({int(round(i * step)) for i in range(max_n)})
    out: list[dict[str, Any]] = []
    for i in idxs:
        p = sorted_pts[i]
        ts = p.get("timestamp")
        if not isinstance(ts, datetime):
            continue
        occ = float(p.get("occupancy_rate") or 0.0)
        fr = float(p.get("female_ratio") or 0.0)
        out.append(
            {
                "t": _iso(ts),
                "occupancy": round(occ, 4),
                "female_ratio": round(fr, 4),
            }
        )
    return out


def _serialize_windows(windows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for w in windows:
        out.append(
            {
                "start": _iso(w.get("start")),
                "end": _iso(w.get("end")),
                "duration_minutes": w.get("duration_minutes"),
                "avg_score": w.get("avg_score"),
            }
        )
    return out


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _parse_store_list(value: str | None) -> list[str]:
    if not value:
        return []
    raw = value.replace(",", " ").split()
    return [item.strip() for item in raw if item.strip()]


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _supabase_conf() -> tuple[str, str] | None:
    base = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    key = (
        os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        or os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
    )
    if not base or not key:
        return None
    return base, key


def _upsert_weekly_report_to_supabase(
    *,
    store: str,
    date_label: str,
    generated_at: str,
    payload: dict[str, Any],
    source: str = "github_actions_weekly",
) -> None:
    conf = _supabase_conf()
    if conf is None:
        raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY is required for weekly sync")
    base, key = conf
    endpoint = f"{base}/rest/v1/blog_drafts"
    facts_id = f"weekly_{store}"
    # v2: ai_commentary があれば本文として使う。なければページが直接ヒートマップ等を描画するため空に近い文に。
    commentary = payload.get("ai_commentary")
    if isinstance(commentary, str) and commentary.strip():
        mdx_body = commentary.strip()
    else:
        mdx_body = "ヒートマップと「賑わいやすい時間帯」を参考に、来週の来店タイミングを検討してみてください。"
    body = {
        "store_id": f"ol_{store}",
        "store_slug": store,
        "target_date": date_label,
        "facts_id": facts_id,
        "mdx_content": mdx_body,
        "insight_json": payload,
        "source": source,
        "content_type": "weekly",
        "is_published": True,
        "edition": "weekly",
        "public_slug": f"weekly-report-{store}",
        "line_user_id": None,
        "error_message": None,
    }
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
        "User-Agent": DEFAULT_USER_AGENT,
    }
    patch_url = f"{endpoint}?facts_id=eq.{facts_id}"
    patch_req = Request(
        patch_url,
        data=json.dumps(body, ensure_ascii=True).encode("utf-8"),
        headers=headers,
        method="PATCH",
    )
    with urlopen(patch_req, timeout=30) as resp:
        patch_raw = resp.read().decode("utf-8")
    try:
        patch_rows = json.loads(patch_raw)
    except json.JSONDecodeError:
        patch_rows = []
    if isinstance(patch_rows, list) and len(patch_rows) > 0:
        return

    insert_body = dict(body)
    insert_body["id"] = str(uuid.uuid4())
    insert_req = Request(
        endpoint,
        data=json.dumps(insert_body, ensure_ascii=True).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urlopen(insert_req, timeout=30):
        pass


# ---------------------------------------------------------------------------
# v2: 4 Phase 改善用ヘルパー
# ---------------------------------------------------------------------------

JST_OFFSET = timezone(timedelta(hours=9))
DAY_LABELS_JA = ["月", "火", "水", "木", "金", "土", "日"]
# 相席ラウンジの営業時間 (JST 19:00-04:59)。配列順は時系列。
HEATMAP_HOURS = [19, 20, 21, 22, 23, 0, 1, 2, 3, 4]


def _build_day_hour_heatmap(points: list[dict[str, Any]]) -> dict[str, Any]:
    """曜日 × 時間帯の平均混雑度ヒートマップを構築する。

    曜日付けは「夜のセッション」基準: 19:00 開始〜翌 04:59 終了を 1 つの夜として扱う。
    たとえば日曜 00:00 のデータは「土曜の夜」と見なし、土曜行に集計する。
    こうしないと「日曜 00:00 が混雑」のような直感に反する表示になる
    (本来は土曜夜のパーティが続いているため)。
    """
    bucket: dict[tuple[int, int], list[tuple[float, float]]] = {}
    for p in points:
        ts = p.get("timestamp")
        if not isinstance(ts, datetime):
            continue
        ts_jst = ts.astimezone(JST_OFFSET)
        hour = ts_jst.hour
        if hour not in HEATMAP_HOURS:
            continue
        # 0-4 時は前日の「夜」として曜日を 1 日戻す
        if hour < 5:
            day = (ts_jst - timedelta(days=1)).weekday()
        else:
            day = ts_jst.weekday()
        occ = float(p.get("occupancy_rate") or 0.0)
        fr = float(p.get("female_ratio") or 0.0)
        bucket.setdefault((day, hour), []).append((occ, fr))

    cells: list[dict[str, Any]] = []
    max_occ = 0.0
    for day in range(7):
        for hour in HEATMAP_HOURS:
            samples = bucket.get((day, hour), [])
            if samples:
                avg_occ = sum(o for o, _ in samples) / len(samples)
                avg_fr = sum(f for _, f in samples) / len(samples)
                count = len(samples)
            else:
                avg_occ = 0.0
                avg_fr = 0.0
                count = 0
            cells.append(
                {
                    "day": day,
                    "hour": hour,
                    "avg_occupancy": round(avg_occ, 4),
                    "avg_female_ratio": round(avg_fr, 4),
                    "sample_count": count,
                }
            )
            if avg_occ > max_occ:
                max_occ = avg_occ

    return {
        "cells": cells,
        "hour_range": HEATMAP_HOURS,
        "day_labels_ja": DAY_LABELS_JA,
        "max_avg_occupancy": round(max_occ, 4),
    }


def _build_daily_summary(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """直近 7 夜の日別サマリ。各「夜」は 19:00 〜 翌 04:59 を 1 日として集計。

    フロントの「先週はこんな感じだった」セクション用。
    """
    by_night: dict[Any, list[dict[str, float]]] = {}
    for p in points:
        ts = p.get("timestamp")
        if not isinstance(ts, datetime):
            continue
        ts_jst = ts.astimezone(JST_OFFSET)
        hour = ts_jst.hour
        if hour not in HEATMAP_HOURS:
            continue
        # 0-4 時は前日の夜
        night_date = (ts_jst - timedelta(days=1)).date() if hour < 5 else ts_jst.date()
        occ = float(p.get("occupancy_rate") or 0.0)
        fr = float(p.get("female_ratio") or 0.0)
        by_night.setdefault(night_date, []).append({"occ": occ, "fr": fr})

    out: list[dict[str, Any]] = []
    for d in sorted(by_night.keys()):
        rows = by_night[d]
        if not rows:
            continue
        avg_occ = sum(r["occ"] for r in rows) / len(rows)
        peak_occ = max(r["occ"] for r in rows)
        avg_fr = sum(r["fr"] for r in rows) / len(rows)
        out.append(
            {
                "date": d.isoformat(),
                "day_label_ja": DAY_LABELS_JA[d.weekday()],
                "avg_occupancy": round(avg_occ, 4),
                "peak_occupancy": round(peak_occ, 4),
                "avg_female_ratio": round(avg_fr, 4),
                "sample_count": len(rows),
            }
        )
    return out


def _derive_next_week_recommendations(heatmap: dict[str, Any], top_n: int = 3) -> list[dict[str, Any]]:
    """ヒートマップ上位 N セルを「来週の狙い目時間」として推奨する。

    Phase D。「先週このパターンだったから、来週も同じ時間帯が狙い目」という
    意思決定材料を提供する。あくまで先週のデータに基づく経験則であり、
    今週の特異事象は反映されない点を UI 側で明示する想定。
    """
    cells = heatmap.get("cells") or []
    # サンプル数が少ないセル (n<2) はノイズとして除外
    filtered = [c for c in cells if (c.get("sample_count") or 0) >= 2 and (c.get("avg_occupancy") or 0) > 0]
    sorted_cells = sorted(filtered, key=lambda c: c.get("avg_occupancy") or 0, reverse=True)
    top = sorted_cells[:top_n]
    out: list[dict[str, Any]] = []
    for c in top:
        day = c["day"]
        hour = c["hour"]
        end_hour = (hour + 1) % 24
        out.append(
            {
                "day": day,
                "day_label_ja": DAY_LABELS_JA[day],
                "hour": hour,
                "hour_label": f"{hour:02d}:00-{end_hour:02d}:00",
                "avg_occupancy": c.get("avg_occupancy"),
                "avg_female_ratio": c.get("avg_female_ratio"),
            }
        )
    return out


def _compute_metric_interpretations(
    points_count: int,
    period_start: datetime | None,
    period_end: datetime | None,
    baseline: float,
) -> dict[str, Any]:
    """既存メトリクスに「だから何?」の解釈を添える (Phase A)。

    フロントの数値カードに「平常」「やや少なめ」などのラベルを表示するための情報。
    """
    days = 7
    if period_start and period_end:
        days = max(1, (period_end - period_start).days + 1)

    daily_avg = points_count / days if days > 0 else 0
    # 1 日平均 100+ 件で「平常」、50-100 で「やや少なめ」、< 50 で「少ない」
    if daily_avg >= 100:
        volume_label = "平常"
    elif daily_avg >= 50:
        volume_label = "やや少なめ"
    else:
        volume_label = "少ない"

    # 混み具合の基準 (P95) の解釈: 大型店 70+, 中規模 30-70, 小規模 <30
    if baseline >= 70:
        baseline_label = "大型店レベル"
    elif baseline >= 30:
        baseline_label = "中規模店レベル"
    else:
        baseline_label = "小規模店または閑散時間が多め"

    return {
        "daily_avg_count": round(daily_avg, 1),
        "volume_label": volume_label,
        "baseline_label": baseline_label,
        "period_days": days,
    }


def _generate_ai_commentary(
    *,
    store_label: str,
    metrics_interp: dict[str, Any],
    heatmap: dict[str, Any],
    daily_summary: list[dict[str, Any]],
    top_windows: list[dict[str, Any]],
    next_week_recs: list[dict[str, Any]],
) -> dict[str, str] | None:
    """Gemini REST API で週報の自然文解説を 2 セクション分生成する (Phase C v2)。

    返り値: {"last_week_summary": "...", "next_week_forecast": "..."} or None。

    `INSIGHTS_GENERATE_AI_COMMENTARY=1` かつ `GEMINI_API_KEY` 設定時のみ動作。
    """
    if not _env_bool("INSIGHTS_GENERATE_AI_COMMENTARY", False):
        return None
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return None

    cells = heatmap.get("cells") or []
    top_cells = sorted(
        [c for c in cells if (c.get("sample_count") or 0) >= 2],
        key=lambda c: c.get("avg_occupancy") or 0,
        reverse=True,
    )[:3]

    payload_for_ai = {
        "store": store_label,
        "metrics": metrics_interp,
        "daily_summary": [
            {
                "date": d["date"],
                "day": d["day_label_ja"],
                "avg_pct": round((d.get("avg_occupancy") or 0) * 100, 1),
                "peak_pct": round((d.get("peak_occupancy") or 0) * 100, 1),
            }
            for d in daily_summary
        ],
        "top_heatmap_cells": [
            {
                "day": DAY_LABELS_JA[c["day"]],
                "hour": c["hour"],
                "occupancy_pct": round((c.get("avg_occupancy") or 0) * 100, 1),
            }
            for c in top_cells
        ],
        "next_week_recommendations": [
            {
                "day": r["day_label_ja"],
                "time": r["hour_label"],
                "occupancy_pct": round((r.get("avg_occupancy") or 0) * 100, 1),
            }
            for r in next_week_recs
        ],
    }

    system_instruction = (
        "あなたは MEGRIBI の週次データ解説ライター。"
        "1 週間の混雑データを読み、相席ラウンジ来店検討者向けに『先週の傾向』と"
        "『来週の予想傾向』を Markdown で簡潔に伝える。\n\n"
        "■ 業態\n"
        "対象は相席ラウンジ。キャバクラ・クラブ (接客型) ではない。"
        "キャバクラ、キャスト、指名、同伴、シャンパン、ホステスなどの語は禁止。\n\n"
        "■ トーン (重要)\n"
        "標準的な情報記事の口調。です・ます調を基本とする。\n"
        "客観的・落ち着いた表現:「〜の傾向です」「〜が見られました」「〜になりそうです」。\n"
        "禁止: 「〜だね」「〜よ」「〜みたい」「〜かもね」のような砕けた語尾。"
        "営業文句 (ぜひお越しください等)。挨拶。\n\n"
        "■ 構成 (どちらを選んでもよい)\n"
        "A. 1〜2 段落の自然文 (読み物として読みたい場合)。\n"
        "B. 短いリード 1 文 + 3〜5 項目の Markdown 箇条書き (`- ` で始まる行)。\n"
        "読みやすさを優先して使い分ける。曜日や時間帯の特徴が複数ある場合は B が向く。\n\n"
        "■ 内容ガイド\n"
        "- 0-4 時のデータは前日の夜セッションとして集計済み (例: 日曜 00:00 は土曜の夜)。\n"
        "- 具体的な曜日・時間帯・%値を必要なだけ盛り込む (羅列しすぎない)。\n"
        "- 「先週」と「来週」で異なる時制を保つ (先週=過去/観察、来週=推量)。\n\n"
        "■ 出力 (JSON 形式)\n"
        "{\n"
        '  "last_week_summary": "<先週の傾向。150-280 字。過去形・観察。'
        "どの曜日 / 時間帯が賑わっていたか、ピークが遅い日や週末以外の盛り上がりなど特徴を抽出>\",\n"
        '  "next_week_forecast": "<来週の予想。100-200 字。推量形。'
        "先週のパターンが続けばどの曜日 / 時間帯が狙い目か。連休やイベントによる変動の可能性があれば短く添える>\"\n"
        "}\n"
        "JSON 以外の文字 (説明、コードフェンス) は一切出力しない。"
        "値の文字列内では Markdown 記法 (`- ` 箇条書き、改行) を自由に使ってよい。"
    )

    user_prompt = (
        "次の JSON は 1 週間分の混雑データの要約です。これを踏まえて、"
        "「先週の傾向」と「来週の予想傾向」の 2 つの段落を生成してください。\n\n"
        + json.dumps(payload_for_ai, ensure_ascii=False, indent=2)
    )

    body = {
        "system_instruction": {"parts": [{"text": system_instruction}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "temperature": 0.7,
            # 1200 だと 2 段落で稀に切断され parse 失敗するため余裕を持たせる
            "maxOutputTokens": 2000,
            "responseMimeType": "application/json",
            # responseSchema で 2 フィールドを強制し、Gemini 側で JSON エスケープも正しく処理させる
            "responseSchema": {
                "type": "OBJECT",
                "properties": {
                    "last_week_summary": {
                        "type": "STRING",
                        "description": "先週の傾向を 150-250 字で。過去形・観察形中心。",
                    },
                    "next_week_forecast": {
                        "type": "STRING",
                        "description": "来週の予想を 100-200 字で。推量形中心。",
                    },
                },
                "required": ["last_week_summary", "next_week_forecast"],
            },
        },
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    req = Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"[weekly-insights] gemini commentary failed: {exc}", file=sys.stderr)
        return None

    try:
        candidates = payload.get("candidates") or []
        if not candidates:
            return None
        parts = (candidates[0].get("content") or {}).get("parts") or []
        raw = "".join(p.get("text", "") for p in parts).strip()
        if not raw:
            return None
        # 1) 通常の JSON parse を試す
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as primary_err:
            # 2) フォールバック: 正規表現で 2 フィールドを抽出
            print(
                f"[weekly-insights] gemini commentary primary parse failed ({primary_err}); "
                f"falling back to regex extraction",
                file=sys.stderr,
            )
            parsed = _extract_commentary_via_regex(raw)
            if parsed is None:
                # 3) 切断などで parse 不可 → 諦めて None を返し UI 側でフォールバック
                print(
                    f"[weekly-insights] gemini commentary regex fallback also failed; raw head={raw[:200]!r}",
                    file=sys.stderr,
                )
                return None
        last = (parsed.get("last_week_summary") or "").strip()
        nxt = (parsed.get("next_week_forecast") or "").strip()
        if not last and not nxt:
            return None
        return {"last_week_summary": last, "next_week_forecast": nxt}
    except Exception as exc:  # noqa: BLE001
        print(f"[weekly-insights] gemini commentary parse failed: {exc}", file=sys.stderr)
        return None


def _extract_commentary_via_regex(raw: str) -> dict[str, str] | None:
    """JSON parse 失敗時のフォールバック: 正規表現で 2 フィールドを抜き出す。

    Gemini が引用符をエスケープせずに改行混じりで返すケースを救う。
    取れた分だけ返し、両方空なら None。
    """
    import re

    out: dict[str, str] = {}
    for key in ("last_week_summary", "next_week_forecast"):
        # "key": "..." を貪欲一致で。閉じ引用符の前は \" でエスケープされていないことを許容
        m = re.search(rf'"{key}"\s*:\s*"((?:[^"\\]|\\.)*)"', raw, re.DOTALL)
        if m:
            text = m.group(1).replace("\\n", "\n").replace('\\"', '"').strip()
            if text:
                out[key] = text
    if not out:
        return None
    return out


def _call_find_good_windows(points: list[dict[str, Any]], **kwargs: Any) -> list[dict[str, Any]]:
    sig = inspect.signature(find_good_windows)
    accepts_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
    if accepts_var_kw:
        return find_good_windows(points, **kwargs)
    filtered = {key: value for key, value in kwargs.items() if key in sig.parameters}
    return find_good_windows(points, **filtered)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stores", help="comma/space separated store slugs")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--threshold", type=float)
    parser.add_argument("--min-duration-minutes", type=int)
    parser.add_argument("--ideal", type=float)
    parser.add_argument("--gender-weight", type=float)
    parser.add_argument(
        "--skip-index",
        action="store_true",
        default=False,
        help="index.json の更新をスキップする（matrix 並列ジョブ用）",
    )
    args = parser.parse_args()

    stores_value = args.stores or os.environ.get("INSIGHTS_STORES")
    stores = _parse_store_list(stores_value)
    if not stores:
        raise SystemExit("stores are required. Use --stores or INSIGHTS_STORES.")

    threshold = args.threshold if args.threshold is not None else _env_float("INSIGHTS_THRESHOLD", DEFAULT_SCORE_THRESHOLD)
    min_duration_minutes = (
        args.min_duration_minutes
        if args.min_duration_minutes is not None
        else _env_int("INSIGHTS_MIN_DURATION_MINUTES", DEFAULT_MIN_DURATION_MINUTES)
    )
    ideal = args.ideal if args.ideal is not None else _env_float("INSIGHTS_IDEAL", DEFAULT_IDEAL)
    gender_weight = (
        args.gender_weight
        if args.gender_weight is not None
        else _env_float("INSIGHTS_GENDER_WEIGHT", DEFAULT_GENDER_WEIGHT)
    )
    timeout_seconds = max(1, _env_int("INSIGHTS_HTTP_TIMEOUT_SECONDS", DEFAULT_HTTP_TIMEOUT_SECONDS))
    retries = max(1, _env_int("INSIGHTS_HTTP_RETRIES", DEFAULT_HTTP_RETRIES))
    sync_to_supabase = _env_bool("INSIGHTS_SYNC_SUPABASE", False)

    base_url = (
        os.environ.get("MEGRIBI_BASE_URL")
        or os.environ.get("NEXT_PUBLIC_BASE_URL")
        or DEFAULT_BASE_URL
    )

    base_dir = REPO_ROOT / "frontend" / "content" / "insights" / "weekly"
    _ensure_dir(base_dir)

    index_path = base_dir / "index.json"
    index_payload: dict[str, Any] = {}
    if index_path.exists():
        try:
            index_payload = json.loads(index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            index_payload = {}

    stores_index = index_payload.get("stores")
    if not isinstance(stores_index, dict):
        stores_index = {}

    now = datetime.now(timezone.utc)
    date_label = now.date().isoformat()
    generated_at = _iso(now)

    for store in stores:
        rows = _load_rows(
            base_url,
            store,
            args.limit,
            timeout_seconds=timeout_seconds,
            retries=retries,
            user_agent=DEFAULT_USER_AGENT,
        )
        timestamps = [ts for ts in (_parse_timestamp(r) for r in rows) if ts is not None]
        period_start = min(timestamps) if timestamps else None
        period_end = max(timestamps) if timestamps else None

        totals = _collect_totals(rows)
        baseline = _percentile(totals, 95.0) if totals else 0.0
        baseline = baseline if baseline > 0 else 0.0

        points = _build_points(rows, baseline)
        windows = _call_find_good_windows(
            points,
            score_threshold=threshold,
            min_duration_minutes=min_duration_minutes,
            ideal=ideal,
            gender_weight=gender_weight,
        )
        serialized_windows = _serialize_windows(windows)
        top_windows = sorted(
            serialized_windows,
            key=lambda w: w.get("avg_score") or 0,
            reverse=True,
        )[:3]

        # v2: Phase A/B/D の追加データを構築
        heatmap = _build_day_hour_heatmap(points)
        daily_summary = _build_daily_summary(points)
        next_week_recs = _derive_next_week_recommendations(heatmap)
        metrics_interp = _compute_metric_interpretations(
            points_count=len(points),
            period_start=period_start,
            period_end=period_end,
            baseline=baseline,
        )

        payload = {
            "analysis_id": f"weekly:{store}:{date_label}",
            "type": "weekly",
            "store": store,
            "generated_at": generated_at,
            "period": {"start": _iso(period_start), "end": _iso(period_end)},
            "params": {
                "threshold": threshold,
                "min_duration_minutes": min_duration_minutes,
                "ideal": ideal,
                "gender_weight": gender_weight,
                "occupancy_baseline": baseline,
            },
            "metrics": {
                "points_used": len(points),
                "baseline_p95_total": baseline,
                "reliability_score": min(1.0, len(points) / 200.0),
            },
            # v2: Phase A
            "metric_interpretations": metrics_interp,
            "windows": serialized_windows,
            "top_windows": top_windows,
            "series_compact": _series_compact_points(points),
            # v2: Phase B
            "day_hour_heatmap": heatmap,
            # v2: Phase D
            "next_week_recommendations": next_week_recs,
            # v2 追補: 日別サマリ (先週何が起きたか の視覚化用)
            "daily_summary": daily_summary,
        }

        # v2: Phase C — AI 自然文解説 (Gemini API key + フラグ ON のときのみ)
        # v2.1: last_week_summary + next_week_forecast の 2 セクション分割
        commentary = _generate_ai_commentary(
            store_label=store,
            metrics_interp=metrics_interp,
            heatmap=heatmap,
            daily_summary=daily_summary,
            top_windows=top_windows,
            next_week_recs=next_week_recs,
        )
        if commentary:
            if commentary.get("last_week_summary"):
                payload["last_week_summary"] = commentary["last_week_summary"]
            if commentary.get("next_week_forecast"):
                payload["next_week_forecast"] = commentary["next_week_forecast"]
            # 後方互換: 旧 ai_commentary 参照箇所のために連結も保持
            joined_parts = [v for v in (commentary.get("last_week_summary"), commentary.get("next_week_forecast")) if v]
            if joined_parts:
                payload["ai_commentary"] = "\n\n".join(joined_parts)

        store_dir = base_dir / store
        _ensure_dir(store_dir)
        out_path = store_dir / f"{date_label}.json"
        with out_path.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=True, indent=2)
            handle.write("\n")

        stores_index[store] = {"latest_file": out_path.name, "generated_at": generated_at}
        if sync_to_supabase:
            _upsert_weekly_report_to_supabase(
                store=store,
                date_label=date_label,
                generated_at=generated_at,
                payload=payload,
            )

    if args.skip_index:
        return 0

    index_payload["generated_at"] = generated_at
    index_payload["stores"] = stores_index
    with index_path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(index_payload, handle, ensure_ascii=True, indent=2)
        handle.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
