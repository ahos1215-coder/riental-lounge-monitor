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
sys.path.insert(0, str(Path(__file__).resolve().parent))
from commentary_quality_gate import check_weekly_commentary  # noqa: E402
from _supabase_common import _supabase_conf  # noqa: E402

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
try:
    from oriental.ml.night_type import NIGHT_SESSION_SHIFT_HOURS  # noqa: E402
except ModuleNotFoundError:
    # 最小依存環境(oriental/__init__.py 経由のimportがflask等を引き込めない場合)では
    # ファイル直読みで代替する。scripts/snapshot_forecasts.py / build_templates.py と同一パターン。
    _night_type_spec = importlib.util.spec_from_file_location(
        "_night_type_standalone", REPO_ROOT / "oriental" / "ml" / "night_type.py"
    )
    _night_type_mod = importlib.util.module_from_spec(_night_type_spec)
    assert _night_type_spec and _night_type_spec.loader
    _night_type_spec.loader.exec_module(_night_type_mod)
    NIGHT_SESSION_SHIFT_HOURS = _night_type_mod.NIGHT_SESSION_SHIFT_HOURS

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

# 新規コメンタリー生成が失敗/ゲート却下された際、既存 Supabase レコードの文章を
# 引き継いでよい最大経過日数。これを超えたら「1年前の先週」のような陳腐化した
# 文章を新しい期間のレポートとして出し続けてしまうため、carry-over を止めて
# 空のまま公開 (フロントはヒートマップのみ表示にフォールバック) し、運用に通知する。
WEEKLY_COMMENTARY_MAX_AGE_DAYS = 21


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


STORES_JSON_PATH = REPO_ROOT / "frontend" / "src" / "data" / "stores.json"


def _load_all_store_slugs() -> list[str]:
    """`--stores all` / `INSIGHTS_STORES=all` 用: stores.json の全店舗 slug を返す。

    ローカル実行で 42 店舗を 1 回でカバーするための便宜機能
    （2026-07-11 sapporo_ag 閉店で 44→42 に変更。stores.json が単一ソース）。
    """
    if not STORES_JSON_PATH.exists():
        raise SystemExit(f"stores.json not found: {STORES_JSON_PATH}")
    data = json.loads(STORES_JSON_PATH.read_text(encoding="utf-8"))
    slugs: list[str] = []
    for row in data:
        slug = row.get("slug")
        if slug:
            slugs.append(slug)
    return slugs


_SLUG_TO_STORE_ID_CACHE: dict[str, str] | None = None


def _load_slug_to_store_id_map() -> dict[str, str]:
    """stores.json (PR #28 で単一ソース化済み) から slug -> store_id の対応表を読み込む。

    oriental/utils/stores.py や multi_collect.py と同じ出典。1プロセス内で1回だけ
    読み込みキャッシュする。stores.json が存在しない/壊れている場合は空の dict を
    返し、呼び出し側 (_store_id_for_slug) のフォールバックに委ねる。
    """
    global _SLUG_TO_STORE_ID_CACHE
    if _SLUG_TO_STORE_ID_CACHE is not None:
        return _SLUG_TO_STORE_ID_CACHE

    mapping: dict[str, str] = {}
    if STORES_JSON_PATH.exists():
        try:
            data = json.loads(STORES_JSON_PATH.read_text(encoding="utf-8"))
            for row in data:
                slug = row.get("slug")
                store_id = row.get("store_id")
                if slug and store_id:
                    mapping[slug] = store_id
        except (json.JSONDecodeError, OSError) as exc:  # noqa: BLE001
            print(f"[weekly-insights] failed to load stores.json for store_id mapping: {exc}", file=sys.stderr)
    else:
        print(f"[weekly-insights] stores.json not found for store_id mapping: {STORES_JSON_PATH}", file=sys.stderr)

    _SLUG_TO_STORE_ID_CACHE = mapping
    return mapping


def _store_id_for_slug(slug: str) -> str:
    """週次レポートの store slug (例: shibuya, shibuya_ag, ay_niigata) から
    Supabase blog_drafts.store_id を解決する。

    店舗マスタは stores.json (PR #28 で単一ソース化) の `store_id` フィールド。
    ブランド判定は slug の見た目 (`_ag` サフィックス等) からは行えない
    (`_ag` は oriental の AG サブブランドで store_id は `ol_*`、相席屋は `ay_`
    プレフィックスの slug で store_id もそのまま `ay_*`)。stores.json に slug が
    見つからない場合は、ジョブを落とさないよう旧来の `ol_{slug}` にフォールバック
    しつつ、大きく警告を出す。
    """
    mapping = _load_slug_to_store_id_map()
    store_id = mapping.get(slug)
    if store_id:
        return store_id
    fallback = f"ol_{slug}"
    print(
        f"[weekly-insights] WARNING: slug={slug!r} not found in stores.json; "
        f"falling back to {fallback!r} (may be incorrect for non-oriental brands)",
        file=sys.stderr,
    )
    return fallback


def _load_store_active_map() -> dict[str, bool]:
    """stores.json の任意フィールド `active` を slug -> bool で読み込む (fix #5)。

    明示的に `active=false` の店舗は週報生成を止めるための「手動オーバーライド」。
    フィールドが無い店舗は既定で有効 (map に載らない = None 扱い)。fix #5 の第一義は
    データ駆動の鮮度チェック (収集が再開すれば自動回復する) で、この active フラグは
    それを上書きする明示スイッチという位置づけ。stores.json が壊れていても週報全体を
    止めないよう、失敗時は空 dict を返す (= 全店 active 扱い)。
    """
    mapping: dict[str, bool] = {}
    if not STORES_JSON_PATH.exists():
        return mapping
    try:
        data = json.loads(STORES_JSON_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:  # noqa: BLE001
        print(f"[weekly-insights] failed to load stores.json for active map: {exc}", file=sys.stderr)
        return mapping
    for row in data:
        slug = row.get("slug")
        active = row.get("active")
        if slug and isinstance(active, bool):
            mapping[slug] = active
    return mapping


def _weekly_skip_reason(
    *,
    store: str,
    active_map: dict[str, bool],
    period_end: datetime | None,
    now: datetime,
    stale_days: int,
) -> str | None:
    """この店舗の週報生成をスキップすべき理由を返す。生成してよければ None (fix #5)。

    1) stores.json で `active=false` に設定されている (明示オーバーライド)
    2) 最新データ (period_end) が取得できない
    3) 最新データが `stale_days` 日より古い (収集停止店の陳腐化データ焼き直し防止)

    (2)(3) はデータ駆動で自己回復する: 収集が再開して新しいデータが入れば、次回以降は
    自動的に生成が再開される。
    """
    if active_map.get(store) is False:
        return "stores.json で active=false に設定されています (手動オーバーライド)"
    if period_end is None:
        return "タイムスタンプ付きデータが取得できませんでした (/api/range が空)"
    age_days = (now - period_end).total_seconds() / 86400.0
    if age_days > stale_days:
        return (
            f"最新データが {age_days:.1f} 日前で古すぎます "
            f"(> WEEKLY_STALE_DAYS={stale_days}); 最新={_iso(period_end)}"
        )
    return None


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


def _fetch_existing_weekly_commentary(store: str) -> dict[str, Any]:
    """既存の Weekly Report レコードから AI コメンタリーフィールドを取得。

    新規生成が 429 等で失敗した場合に、前回の文章を保持するために使う。
    取得失敗・存在しない場合は空 dict。

    返り値には本文 3 フィールドに加え、鮮度判定用の `_existing_generated_at`
    (insight_json.generated_at があればそれ、無ければ行の updated_at/created_at) を
    ISO 文字列で含める。呼び出し側はこれで carry-over の年齢を判定できる
    (WEEKLY_COMMENTARY_MAX_AGE_DAYS)。
    """
    conf = _supabase_conf()
    if conf is None:
        return {}
    base, key = conf
    facts_id = f"weekly_{store}"
    url = (
        f"{base}/rest/v1/blog_drafts"
        f"?facts_id=eq.{facts_id}&select=insight_json,updated_at,created_at&limit=1"
    )
    try:
        req = Request(
            url,
            headers={
                "apikey": key,
                "Authorization": f"Bearer {key}",
                "Accept": "application/json",
            },
        )
        with urlopen(req, timeout=15) as resp:
            rows = json.loads(resp.read().decode("utf-8"))
        if not isinstance(rows, list) or not rows:
            return {}
        row = rows[0] or {}
        ij = row.get("insight_json") or {}
        out: dict[str, Any] = {}
        for k in ("last_week_summary", "next_week_forecast", "ai_commentary"):
            v = ij.get(k)
            if isinstance(v, str) and v.strip():
                out[k] = v
        existing_generated_at = (
            ij.get("generated_at") or row.get("updated_at") or row.get("created_at")
        )
        if isinstance(existing_generated_at, str) and existing_generated_at.strip():
            out["_existing_generated_at"] = existing_generated_at
        return out
    except Exception as exc:  # noqa: BLE001
        print(f"[weekly-insights] fetch existing commentary failed: {exc}", file=sys.stderr)
        return {}


def _commentary_age_days(existing_generated_at: str | None, *, now: datetime) -> float | None:
    """既存コメンタリーの生成時刻からの経過日数を返す。パース不可なら None
    (= 年齢不明。呼び出し側は安全側に倒して carry-over を許可する)。"""
    if not existing_generated_at:
        return None
    raw = existing_generated_at.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = now.astimezone(timezone.utc) - dt.astimezone(timezone.utc)
    return delta.total_seconds() / 86400.0


def _notify_ops(message: str) -> None:
    """OPS_NOTIFY_WEBHOOK_URL (Slack/Discord) へ best-effort で POST する。

    未設定なら no-op。失敗しても例外は投げない (呼び出し元の処理を止めないため)。
    scripts/score_forecasts.py の `_alert` と同じ規約 ({"text": message} を POST)。
    """
    url = (os.environ.get("OPS_NOTIFY_WEBHOOK_URL") or "").strip()
    if not url:
        print(f"[weekly-insights][alert] (OPS_NOTIFY_WEBHOOK_URL unset) {message}", file=sys.stderr)
        return
    try:
        req = Request(
            url,
            data=json.dumps({"text": message}).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urlopen(req, timeout=15):
            pass
        print(f"[weekly-insights][alert] sent: {message}", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001
        print(f"[weekly-insights][alert] failed to send: {str(exc)[:200]}", file=sys.stderr)


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
        "store_id": _store_id_for_slug(store),
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

# 夜セッションを跨ぐ間隙 (04:59→翌19:00 の ~14h) を「賑わい窓」の途切れとして扱う閾値。
# 直近7夜へ切り詰めた points は日中サンプルを含まないため、隣接する夜が地続きに
# 見えてしまう。観測間隔 (概ね 5-15 分) を大きく超える間隙で窓を分割する (fix #2)。
DEFAULT_BUSY_MAX_GAP_MINUTES = 30

# 週報バッチが「収集停止済み店舗」の 2ヶ月前データを毎週「今日更新」で焼き直すのを防ぐ
# 鮮度上限 (fix #5)。最新データがこの日数より古ければその店舗はスキップする。env override。
DEFAULT_WEEKLY_STALE_DAYS = 10

# 1 夜あたりの最小観測数 (fix #12)。これ未満の夜は low_sample フラグを立て、
# フロントの「一番賑わった夜」の断定 (WeeklySummary の busiest) から除外できるようにする。
# 健全な夜は概ね ~120 件 (10 時間 × 5 分間隔)。その ~20% (=24) を下限の目安とする。env override。
DEFAULT_WEEKLY_MIN_NIGHT_SAMPLES = 24


def _night_date(ts_jst: datetime) -> Any:
    """JST タイムスタンプが属する「夜」の日付 (date) を返す。

    夜のセッションは 19:00 開始〜翌 04:59 終了。0-5 時台 (00:00-05:59) のデータは前夜の
    セッションとして扱う (-6h シフト規約。oriental/ml/night_type.py の
    NIGHT_SESSION_SHIFT_HOURS / postprocess.py と同一の単一ソース)。
    例: 日曜 00:00 は土曜の夜。HEATMAP_HOURS 外 (日中 6-18 時) の点をどう扱うかは
    呼び出し側の責務 (通常は事前に HEATMAP_HOURS でフィルタしてから渡す)。

    2026-07-11: 旧実装は独自に `hour < 5` (-5h相当) を使っており night_type.py の
    -6h規約と1時間ずれていた。実データでは収集が ~04:55 JST で止まり JST 5時台の行が
    存在しない (直近7日で0件を確認) ため、この統一によるレポート出力への実影響はゼロ
    (詳細は CLAUDE.md「よくある罠」#2)。
    """
    return (
        (ts_jst - timedelta(days=1)).date()
        if ts_jst.hour < NIGHT_SESSION_SHIFT_HOURS
        else ts_jst.date()
    )


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
        day = _night_date(ts_jst).weekday()
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


WEEKLY_DAILY_SUMMARY_MAX_NIGHTS = 7


def _truncate_points_to_recent_nights(
    points: list[dict[str, Any]],
    max_nights: int = WEEKLY_DAILY_SUMMARY_MAX_NIGHTS,
) -> list[dict[str, Any]]:
    """全 consumer が同一の「直近 N 夜」を見るよう、points を上流で 1 度だけ切り詰める (fix #6)。

    フェッチ元 API の `--limit` は 8〜10 夜分を返し得るが、レポートは「直近7夜」を謳う。
    従来は daily_summary だけが内部で 7 夜に切り詰め、ヒートマップ / 狙い目TOP3 /
    AIコメンタリー入力は切り詰め前の全夜を使っていたため、
      - ヒートマップの sample_count が daily_summary より多い (同一曜日に 8 夜目が二重計上。
        実例 ebisu 2026-07-07: 火曜セルが 24 件 = 2 夜分)
      - 「集計期間=直近7夜」と実データがずれる
      - AI の数値グラウンディングゲートは 7 夜を真値としているのにヒートマップは 8 夜を見る
    という不整合が生じていた。ここで points 自体を直近 N 夜へ揃え、全 consumer を一致させる。

    夜セッション (HEATMAP_HOURS, 19:00〜翌04:59) に属する点のみを対象とし、日中 (5-18 時)
    の点は夜レポートの母集団ではないため落とす。結果として heatmap の総 sample_count と
    daily_summary の総 sample_count は一致する。
    """
    nights: set[Any] = set()
    for p in points:
        ts = p.get("timestamp")
        if not isinstance(ts, datetime):
            continue
        ts_jst = ts.astimezone(JST_OFFSET)
        if ts_jst.hour not in HEATMAP_HOURS:
            continue
        nights.add(_night_date(ts_jst))
    if not nights:
        return []
    kept = set(sorted(nights)[-max_nights:])

    out: list[dict[str, Any]] = []
    for p in points:
        ts = p.get("timestamp")
        if not isinstance(ts, datetime):
            continue
        ts_jst = ts.astimezone(JST_OFFSET)
        if ts_jst.hour not in HEATMAP_HOURS:
            continue
        if _night_date(ts_jst) in kept:
            out.append(p)
    return out


def _build_daily_summary(
    points: list[dict[str, Any]],
    *,
    min_night_samples: int = DEFAULT_WEEKLY_MIN_NIGHT_SAMPLES,
) -> list[dict[str, Any]]:
    """直近 7 夜の日別サマリ。各「夜」は 19:00 〜 翌 04:59 を 1 日として集計。

    フロントの「先週はこんな感じだった」セクション用。

    注意: 入力 `points` にはフェッチ元 API の `--limit` に応じて 7 夜を超える
    夜が含まれ得る (実例: fukuoka 2026-07-03 で 9 夜分が混入していた)。
    ここで直近 (日付が新しい方から) WEEKLY_DAILY_SUMMARY_MAX_NIGHTS 夜だけを
    残すことで、docstring/フロント表記の「先週7夜」を実態と一致させる。

    fix #12: 観測数が `min_night_samples` 未満の夜は `low_sample=True` を立てる。
    ヒートマップは sample_count>=2 のセルだけを狙い目/AI入力に使うのに、日別サマリには
    足切りが無く、観測の薄い夜 (実例: kokura 07-01=6件, utsunomiya 07-06=17件) を
    「一番賑わった夜」と同じ確信度で断定し得た。フラグを持たせ、フロント側で
    busiest 判定から外せるようにする (夜自体は集計/カウント整合のため残す)。
    """
    by_night: dict[Any, list[dict[str, float]]] = {}
    for p in points:
        ts = p.get("timestamp")
        if not isinstance(ts, datetime):
            continue
        ts_jst = ts.astimezone(JST_OFFSET)
        if ts_jst.hour not in HEATMAP_HOURS:
            continue
        night_date = _night_date(ts_jst)
        occ = float(p.get("occupancy_rate") or 0.0)
        fr = float(p.get("female_ratio") or 0.0)
        by_night.setdefault(night_date, []).append({"occ": occ, "fr": fr})

    # 直近 N 夜だけを残す (日付が新しい方から N 件 → 昇順に戻す)
    kept_nights = sorted(by_night.keys())[-WEEKLY_DAILY_SUMMARY_MAX_NIGHTS:]

    out: list[dict[str, Any]] = []
    for d in kept_nights:
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
                # fix #12: 観測が薄い夜は「一番賑わった夜」の断定から除外させるためのフラグ
                "low_sample": len(rows) < int(min_night_samples),
            }
        )
    return out


def _build_busy_windows(
    points: list[dict[str, Any]],
    occupancy_threshold: float,
    min_duration_minutes: int,
    max_gap_minutes: float = DEFAULT_BUSY_MAX_GAP_MINUTES,
) -> list[dict[str, Any]]:
    """「賑わいやすい時間帯」を素の混雑度 (occupancy_rate) だけで検出する (fix #2)。

    従来は megribi_score (女性比重み付き × ideal=0.7 で頭打ちの合成スコア) で窓を
    選んでいたため、満席 (occ≈1.0) の時間帯は occ_score が 0 に落ちて脱落し、逆に
    ideal 付近 (occ≈0.7) かつ女性比の高い「日中の空いた時間」が上位に来る自己矛盾が
    起きていた (実例: ebisu 2026-07-07 は土 22:00-01:00 が満席なのに賑わい窓は 11:00 台の
    日中窓だった)。同じページの狙い目TOP3 は素の occupancy を使っており正しかったため、
    賑わい窓も素の occupancy に統一し、両セクションが矛盾しないようにする。

    occupancy_rate が occupancy_threshold 以上の点が連続する区間を 1 窓とし、観測間隔を
    大きく超える間隙 (max_gap_minutes) では窓を分割する (直近7夜へ切り詰めた points は
    日中サンプルを含まず、夜を跨いで地続きに見えるのを防ぐ)。avg_score には平均 occupancy を
    格納する (フロントの scoreLabel 閾値 0.6/0.45 とも意味的に整合する)。
    """
    scored: list[tuple[datetime, float]] = []
    for p in points:
        ts = p.get("timestamp")
        if not isinstance(ts, datetime):
            continue
        occ = float(p.get("occupancy_rate") or 0.0)
        scored.append((ts, occ))
    scored.sort(key=lambda item: item[0])

    windows: list[dict[str, Any]] = []
    segment: list[tuple[datetime, float]] = []
    threshold = float(occupancy_threshold)

    def flush_segment() -> None:
        if not segment:
            return
        start_dt = segment[0][0]
        end_dt = segment[-1][0]
        duration_minutes = (end_dt - start_dt).total_seconds() / 60.0
        if duration_minutes >= float(min_duration_minutes):
            avg_occ = sum(o for _, o in segment) / len(segment)
            windows.append(
                {
                    "start": start_dt,
                    "end": end_dt,
                    "duration_minutes": duration_minutes,
                    "avg_score": avg_occ,
                }
            )
        segment.clear()

    prev_dt: datetime | None = None
    for dt, occ in scored:
        if occ >= threshold:
            if prev_dt is not None and (dt - prev_dt).total_seconds() / 60.0 > float(max_gap_minutes):
                flush_segment()
            segment.append((dt, occ))
            prev_dt = dt
        else:
            flush_segment()
            prev_dt = None
    flush_segment()
    return windows


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
    *,
    period_days_override: int | None = None,
) -> dict[str, Any]:
    """既存メトリクスに「だから何?」の解釈を添える (Phase A)。

    フロントの数値カードに「平常」「やや少なめ」などのラベルを表示するための情報。

    `period_days_override`: 呼び出し側が正確な日数 (例: daily_summary が保持した
    夜の件数) を把握している場合に指定する。省略時は period_start/period_end の
    差分から概算する (従来通り)。
    """
    days = 7
    if period_days_override is not None:
        days = max(1, period_days_override)
    elif period_start and period_end:
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
    """週報の自然文解説を 2 セクション分生成する (Phase C v2)。

    バックエンドは `INSIGHTS_LLM_BACKEND` (既定 "ollama") で切り替える:
      - "ollama": ローカル Ollama (gemma4:e4b) を使用。GEMINI_API_KEY 不要。コスト削減版。
      - "gemini": 従来通り Gemini REST API (要 GEMINI_API_KEY)。

    system_instruction / user_prompt はモデル非依存のため共通で組み立て、
    実際の呼び出し・レスポンス抽出だけをバックエンドごとに分岐する。

    返り値: {"last_week_summary": "...", "next_week_forecast": "..."} or None。

    `INSIGHTS_GENERATE_AI_COMMENTARY=1` のときのみ動作。
    """
    if not _env_bool("INSIGHTS_GENERATE_AI_COMMENTARY", False):
        return None

    backend = os.environ.get("INSIGHTS_LLM_BACKEND", "ollama").strip().lower()
    if not backend:
        backend = "ollama"

    api_key = ""
    if backend == "gemini":
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
        "初めて読む人がさっと一読しただけで分かるよう、やさしい普段の言葉で簡潔に書く。です・ます調。\n"
        "客観的・落ち着いた表現:「〜の傾向です」「〜が見られました」「〜になりそうです」。\n"
        "『埋まり具合0.3』のような 0〜1 の生の数値は使わず、% か『空いている/混んでいる/ほぼ満席』で表す。\n"
        "禁止: 「〜だね」「〜よ」「〜みたい」「〜かもね」のような砕けた語尾。"
        "営業文句 (ぜひお越しください等)。挨拶。\n\n"
        "■ 構成 (必ずこの形式)\n"
        "1. リード文 1 行 (40-60 字): 先週/来週の一番のポイントを 1 文で。これだけ読めば要点が伝わるように。\n"
        "2. 改行を 1 つ挟む\n"
        "3. Markdown 箇条書き 2〜3 項目 (`- ` で始まる行): 混みやすい/空きやすい曜日・時間帯を、やさしい言葉で短く。\n"
        "例:\n"
        "先週は週末を中心に混み合いました。\n"
        "\n"
        "- 金曜・土曜の夜: かなり混雑。ピーク時はほぼ満席\n"
        "- 火曜: 平日でも混みやすい日\n"
        "- 月曜・水曜: 比較的ゆったり過ごせる\n\n"
        "■ 内容ガイド\n"
        "- 0-4 時のデータは前日の夜セッションとして集計済み (例: 日曜 00:00 は土曜の夜)。\n"
        "- 具体的な曜日・時間帯・%値を必要なだけ盛り込む (羅列しすぎない)。\n"
        "- 「先週」と「来週」で異なる時制を保つ (先週=過去/観察、来週=推量)。\n"
        "- データに無い事柄 (予約の可否・待ち時間・特典など) は書かない。数値の裏付けがある事実のみ。\n\n"
        "■ 出力 (JSON 形式)\n"
        "{\n"
        '  "last_week_summary": "<リード 1 文 + 改行 + 箇条書き 3-5 項目。過去形・観察>",\n'
        '  "next_week_forecast": "<リード 1 文 + 改行 + 箇条書き 3-5 項目。推量形>"\n'
        "}\n"
        "JSON 以外の文字 (説明、コードフェンス) は一切出力しない。"
        "値の文字列内には必ず Markdown 箇条書き (`- ` で始まる行) を含めること。"
    )

    user_prompt = (
        "次の JSON は 1 週間分の混雑データの要約です。これを踏まえて、"
        "「先週の傾向」と「来週の予想傾向」の 2 つの段落を生成してください。\n\n"
        + json.dumps(payload_for_ai, ensure_ascii=False, indent=2)
    )

    if backend == "ollama":
        raw = _ollama_commentary_call(system_instruction, user_prompt)
        if raw is None:
            return None
        return _parse_commentary_text(raw, backend="ollama")

    # backend == "gemini" (既存の挙動を変更しない)
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
    payload = _gemini_call_with_retry(api_key, body)
    if payload is None:
        return None

    try:
        candidates = payload.get("candidates") or []
        if not candidates:
            return None
        parts = (candidates[0].get("content") or {}).get("parts") or []
        raw = "".join(p.get("text", "") for p in parts).strip()
        if not raw:
            return None
        return _parse_commentary_text(raw, backend="gemini")
    except Exception as exc:  # noqa: BLE001
        print(f"[weekly-insights] gemini commentary parse failed: {exc}", file=sys.stderr)
        return None


def _parse_commentary_text(raw: str, *, backend: str) -> dict[str, str] | None:
    """LLM が返した生テキストを {"last_week_summary", "next_week_forecast"} に変換する。

    バックエンド (ollama/gemini) 共通のロジック:
    1) 通常の json.loads を試す
    2) 失敗したら正規表現フォールバック (_extract_commentary_via_regex)
    3) それでも駄目なら None
    """
    raw = raw.strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as primary_err:
        print(
            f"[weekly-insights] {backend} commentary primary parse failed ({primary_err}); "
            f"falling back to regex extraction",
            file=sys.stderr,
        )
        parsed = _extract_commentary_via_regex(raw)
        if parsed is None:
            print(
                f"[weekly-insights] {backend} commentary regex fallback also failed; raw head={raw[:200]!r}",
                file=sys.stderr,
            )
            return None
    last = _sanitize_commentary_text(parsed.get("last_week_summary") or "")
    nxt = _sanitize_commentary_text(parsed.get("next_week_forecast") or "")
    if not last and not nxt:
        return None
    return {"last_week_summary": last, "next_week_forecast": nxt}


def _sanitize_commentary_text(text: str) -> str:
    """モデル出力の軽微なアーティファクトを除去する。

    観測例 (fukuoka 2026-07-03): 文末の「。」直後に孤立した 'n' が残り
    「〜見込みです。n」のまま公開された (\\n エスケープ崩れの残骸)。
    句点・感嘆・疑問符の直後で行末に孤立する 'n' は日本語文として
    あり得ないため安全に除去できる。"""
    import re

    text = re.sub(r"(?<=[。．！？])n(?=\s*$)", "", text, flags=re.MULTILINE)
    return text.strip()


def _ollama_commentary_call(system_instruction: str, user_prompt: str) -> str | None:
    """ローカル Ollama (gemma4:e4b) を呼び出し、応答テキスト (JSON 文字列想定) を返す。

    共有 GPU ロック (gpu_lock) 配下で呼ぶ (local_report_job.py と同じ取り込み方)。
    gpu_lock が見つからない場合はロック無しで続行 (best-effort)。
    エラー・タイムアウト時は stderr にログして None を返す (例外は投げない)。
    """
    try:
        sys.path.insert(0, r"C:\Users\Public\共有データ系")
        import gpu_lock  # type: ignore
    except Exception:  # noqa: BLE001
        gpu_lock = None

    from contextlib import nullcontext

    body = {
        "model": "gemma4:e4b",
        "messages": [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        # keep_alive="10m": 全店の間モデルのロードを維持し、1店ごとの再ロード(8-11s)を無くす。
        # ラン終了時に main() 末尾で明示アンロードして GPU を音楽PJ等へ返す。
        "keep_alive": "10m",
        # gemma4 は既定で reasoning ON だが、週次要約に推論は不要。ON だと思考で数千トークン
        # 消費し遅く・発熱増になるため OFF (実測 29.4s→13.7s)。
        "think": False,
        # Gemini 側の responseSchema と同様、キー名を綴りごと強制する。小型モデル(e4b)は
        # "json" 指定だけだとキーを稀に誤字る(例: last_week_summaary)ため、スキーマで固定する。
        "format": {
            "type": "object",
            "properties": {
                "last_week_summary": {"type": "string"},
                "next_week_forecast": {"type": "string"},
            },
            "required": ["last_week_summary", "next_week_forecast"],
        },
        # num_gpu=999 で全層 GPU を明示。e4b は VRAM 3.0GB なので ctx8192 でも 100% GPU。
        "options": {"num_ctx": 8192, "num_gpu": 999, "temperature": 0.7},
    }

    # タイムアウト等の一過性エラーで 1 店だけ本文が欠けるのを防ぐため 1 回だけ再試行する
    # (観測例 2026-07-03: ay_shibuya / hiroshima_ag が単発 timeout で欠報になった)。
    # ロックは試行ごとに取得し直し、待ち時間に音楽プロジェクトが割り込めるようにする。
    attempts = 2
    for attempt in range(1, attempts + 1):
        lock_cm = gpu_lock.acquire(owner="meguribi-weekly", timeout=900) if gpu_lock is not None else nullcontext()
        try:
            with lock_cm:
                req = Request(
                    "http://localhost:11434/api/chat",
                    data=json.dumps(body).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(req, timeout=360) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
            text = (payload.get("message") or {}).get("content", "")
            if not text or not text.strip():
                print("[weekly-insights] ollama commentary: empty response content", file=sys.stderr)
                return None
            return text
        except Exception as exc:  # noqa: BLE001
            print(
                f"[weekly-insights] ollama commentary call failed (attempt {attempt}/{attempts}): {exc}",
                file=sys.stderr,
            )
            if attempt < attempts:
                time.sleep(10)
    return None


def _gemini_call_with_retry(api_key: str, body: dict[str, Any]) -> dict[str, Any] | None:
    """Gemini REST API 呼び出し。429 (rate limit) はバックオフで再試行し、
    最終的に gemini-2.5-flash-lite (別クォータ枠) にフォールバックする。

    全モデル・全試行で失敗したら None を返す。
    """
    from urllib.error import HTTPError

    models = ["gemini-2.5-flash", "gemini-2.5-flash-lite"]
    backoffs = [5, 15, 45]  # 秒
    last_error: Exception | None = None

    for model in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        for attempt, wait_sec in enumerate(backoffs):
            req = Request(
                url,
                data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urlopen(req, timeout=30) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except HTTPError as exc:
                last_error = exc
                if exc.code == 429:
                    is_last_attempt = attempt == len(backoffs) - 1
                    if is_last_attempt:
                        print(
                            f"[weekly-insights] {model} 429 quota exhausted after {len(backoffs)} attempts; "
                            f"trying next model",
                            file=sys.stderr,
                        )
                        break  # 次のモデルへ
                    print(
                        f"[weekly-insights] {model} 429, retrying in {wait_sec}s "
                        f"(attempt {attempt + 1}/{len(backoffs)})",
                        file=sys.stderr,
                    )
                    time.sleep(wait_sec)
                    continue
                # 429 以外の HTTP エラーはリトライしない
                print(f"[weekly-insights] {model} HTTP error: {exc}", file=sys.stderr)
                break
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                print(f"[weekly-insights] {model} call failed: {exc}", file=sys.stderr)
                break

    print(
        f"[weekly-insights] gemini commentary failed across all models; last error={last_error}",
        file=sys.stderr,
    )
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
    # fix #2 以降、週報の「賑わいやすい時間帯」はこの合成スコア窓ではなく素の occupancy を
    # 使う _build_busy_windows に置き換わった。このヘルパー/ megribi_score import は将来の
    # 参照・比較用に残しているが、現在レポート生成パイプラインからは呼ばれていない。
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
        help=(
            "廃止済み・no-op（2026-07-18 index.json retirement）。index.json 生成コード"
            "自体を削除済み: frontend 側に読み手がゼロだったこと（weekly report ページは "
            "Supabase blog_drafts から直接取得、sitemap.ts は各店ディレクトリのファイル名"
            "一覧から lastModified を導出）をgrepで確認した上で退役した。"
            "generate-weekly-insights.yml（GHA 緊急手動実行）がまだこのフラグを渡すため、"
            "後方互換のため引数としてのみ残している。"
        ),
    )
    args = parser.parse_args()

    stores_value = args.stores or os.environ.get("INSIGHTS_STORES")
    if stores_value and stores_value.strip().lower() == "all":
        stores = _load_all_store_slugs()
    else:
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
    # fix #5: 収集停止店の陳腐化データ焼き直し防止。最新データがこの日数より古ければスキップ。
    stale_days = max(1, _env_int("WEEKLY_STALE_DAYS", DEFAULT_WEEKLY_STALE_DAYS))
    # fix #12: 1 夜あたり観測数の下限。これ未満の夜は daily_summary で low_sample フラグ付き。
    min_night_samples = max(1, _env_int("WEEKLY_MIN_NIGHT_SAMPLES", DEFAULT_WEEKLY_MIN_NIGHT_SAMPLES))
    # fix #5: 明示オーバーライド用の active フラグ (stores.json)。既定は全店 active。
    active_map = _load_store_active_map()

    base_url = (
        os.environ.get("MEGRIBI_BASE_URL")
        or os.environ.get("NEXT_PUBLIC_BASE_URL")
        or DEFAULT_BASE_URL
    )

    base_dir = REPO_ROOT / "frontend" / "content" / "insights" / "weekly"
    _ensure_dir(base_dir)

    # 2026-07-18 index.json retirement: index.json 生成は退役済み。run_weekly_local.ps1
    # が常に --skip-index を付けて呼んでいたため 2026-06-30 以降 1 度も更新されておらず、
    # かつ frontend 側に index.json の読み手が存在しないことを grep で確認した
    # （weekly report ページ frontend/src/app/reports/weekly/[store_slug]/page.tsx は
    # Supabase blog_drafts から直接取得し、sitemap.ts の lastModified も
    # frontend/content/insights/weekly/<slug>/ 配下のファイル名一覧を fs.readdirSync
    # するだけで index.json を見ない）。集約インデックスは元々不要だった。

    now = datetime.now(timezone.utc)
    date_label = now.date().isoformat()
    generated_at = _iso(now)

    for store in stores:
        # fix #5: 明示オーバーライド (active=false) は HTTP フェッチ前に弾く。
        if active_map.get(store) is False:
            print(
                f"[weekly-insights] SKIP store={store}: stores.json で active=false "
                f"(手動オーバーライド)",
                file=sys.stderr,
            )
            continue

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

        # fix #5: 鮮度チェック。収集停止店 (最新データが stale_days 日より古い) は生成/公開
        # しない。これが無いと sapporo_ag のような停止店が毎週「今日更新」で 2ヶ月前データを
        # 焼き直し、AI が同じ古いデータに毎回新しいコメンタリーを書いてしまう
        # (実例 2026-07-07: 最新 2026-05-11 のデータを generated_at=2026-07-07 で再生成)。
        skip_reason = _weekly_skip_reason(
            store=store,
            active_map=active_map,
            period_end=period_end,
            now=now,
            stale_days=stale_days,
        )
        if skip_reason is not None:
            print(f"[weekly-insights] SKIP store={store}: {skip_reason}", file=sys.stderr)
            continue

        totals = _collect_totals(rows)
        baseline = _percentile(totals, 95.0) if totals else 0.0
        baseline = baseline if baseline > 0 else 0.0

        # fix #6: 全 consumer が同一の「直近7夜」を見るよう、points を上流で 1 度だけ切り詰める。
        # これ以降の heatmap / daily_summary / 賑わい窓 / 狙い目TOP3 / AI入力 / points_used は
        # すべてこの truncated points から作られ、集計期間・件数が完全に一致する。
        points = _truncate_points_to_recent_nights(_build_points(rows, baseline))

        # fix #2: 「賑わいやすい時間帯」は女性比重み付きの合成スコアではなく素の occupancy で
        # ランク付けする (狙い目TOP3 と同じ指標)。満席時間帯が脱落する自己矛盾を解消。
        windows = _build_busy_windows(points, threshold, min_duration_minutes)
        serialized_windows = _serialize_windows(windows)
        top_windows = sorted(
            serialized_windows,
            key=lambda w: w.get("avg_score") or 0,
            reverse=True,
        )[:3]

        # v2: Phase A/B/D の追加データを構築 (すべて truncated points 基準)
        heatmap = _build_day_hour_heatmap(points)
        daily_summary = _build_daily_summary(points, min_night_samples=min_night_samples)
        next_week_recs = _derive_next_week_recommendations(heatmap)

        # _build_daily_summary は直近 WEEKLY_DAILY_SUMMARY_MAX_NIGHTS 夜だけに切り詰める
        # (fukuoka 2026-07-03 実例: フェッチ元の rows に 9 夜分混入していた)。
        # レポート上部の「集計期間」表示や metric_interpretations の period_days が
        # 生の取得ウィンドウ (最大 9 日超) のままだと、"先週7夜" と謳いながら表示される
        # 期間だけ数日分ズレて見える。daily_summary が実際に保持した夜の範囲・件数に
        # period を合わせ、両者を一致させる。
        if daily_summary:
            kept_dates = [d["date"] for d in daily_summary]
            report_period_start = datetime.fromisoformat(min(kept_dates)).replace(tzinfo=JST_OFFSET)
            # 最終夜の営業終了 (翌 04:59 相当) を期間終端として表示する
            report_period_end = datetime.fromisoformat(max(kept_dates)).replace(
                tzinfo=JST_OFFSET
            ) + timedelta(days=1, hours=4, minutes=59)
            report_period_days = len(daily_summary)
        else:
            report_period_start = period_start
            report_period_end = period_end
            report_period_days = None

        metrics_interp = _compute_metric_interpretations(
            points_count=len(points),
            period_start=report_period_start,
            period_end=report_period_end,
            baseline=baseline,
            period_days_override=report_period_days,
        )

        payload = {
            "analysis_id": f"weekly:{store}:{date_label}",
            "type": "weekly",
            "store": store,
            "generated_at": generated_at,
            "period": {"start": _iso(report_period_start), "end": _iso(report_period_end)},
            # フェッチ元 API から返った生データの実際の範囲 (デバッグ・監査用。
            # 上の period はレポート表示/daily_summary と一致させた「表示用」の期間)。
            "raw_fetch_period": {"start": _iso(period_start), "end": _iso(period_end)},
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
            # v2: Phase B
            "day_hour_heatmap": heatmap,
            # v2: Phase D
            "next_week_recommendations": next_week_recs,
            # v2 追補: 日別サマリ (先週何が起きたか の視覚化用)
            "daily_summary": daily_summary,
        }

        # v2: Phase C — AI 自然文解説 (Gemini API key + フラグ ON のときのみ)
        # v2.1: last_week_summary + next_week_forecast の 2 セクション分割
        # v2.2: 失敗時は既存 Supabase レコードから前回文を引き継ぎ、上書き消失を防ぐ
        commentary = _generate_ai_commentary(
            store_label=store,
            metrics_interp=metrics_interp,
            heatmap=heatmap,
            daily_summary=daily_summary,
            top_windows=top_windows,
            next_week_recs=next_week_recs,
        )
        if commentary:
            # v2.3: 公開前の数値グラウンディング検証 (2026-07-03 全44店監査で発見した
            # shinsaibashi 級の数値誤りを block する)。LLM を追加で呼ばない決定的チェック。
            # 詳細: scripts/commentary_quality_gate.py
            gate_ok, gate_reasons = check_weekly_commentary(commentary, daily_summary)
            if not gate_ok:
                print(
                    f"[weekly-insights] commentary quality gate failed for store={store}: "
                    f"{'; '.join(gate_reasons)}",
                    file=sys.stderr,
                )
                commentary = None
        if commentary:
            if commentary.get("last_week_summary"):
                payload["last_week_summary"] = commentary["last_week_summary"]
            if commentary.get("next_week_forecast"):
                payload["next_week_forecast"] = commentary["next_week_forecast"]
            # 後方互換: 旧 ai_commentary 参照箇所のために連結も保持
            joined_parts = [v for v in (commentary.get("last_week_summary"), commentary.get("next_week_forecast")) if v]
            if joined_parts:
                payload["ai_commentary"] = "\n\n".join(joined_parts)
        else:
            # 新規生成失敗 → 既存レコードから前回文を引き継ぐ (sync_to_supabase 時のみ意味あり)。
            # ただし引き継ぎには鮮度上限を設ける (WEEKLY_COMMENTARY_MAX_AGE_DAYS)。
            # これが無いと、生成が恒常的に失敗し続ける店舗で「1年前の先週は〜」が
            # 新しい target_date/period/heatmap と一緒に is_published=true のまま
            # 延々と表示され続け、誰も気づかない致命的な陳腐化になる。
            if sync_to_supabase:
                existing = _fetch_existing_weekly_commentary(store)
                existing_generated_at = existing.get("_existing_generated_at")
                age_days = _commentary_age_days(existing_generated_at, now=now)
                text_keys = ("last_week_summary", "next_week_forecast", "ai_commentary")
                has_existing_text = any(existing.get(k) for k in text_keys)

                if has_existing_text and age_days is not None and age_days > WEEKLY_COMMENTARY_MAX_AGE_DAYS:
                    print(
                        f"[weekly-insights] existing commentary for store={store} is stale "
                        f"({age_days:.1f} days > {WEEKLY_COMMENTARY_MAX_AGE_DAYS}); "
                        f"NOT carrying over, publishing without commentary (heatmap-only)",
                        file=sys.stderr,
                    )
                    _notify_ops(
                        f"[weekly-insights] store={store}: AI commentary generation failed/rejected "
                        f"and the existing Supabase record is {age_days:.1f} days old "
                        f"(> {WEEKLY_COMMENTARY_MAX_AGE_DAYS}d threshold). "
                        f"Stale carry-over was SKIPPED; this week's report will publish "
                        f"without last_week_summary/next_week_forecast. Investigate the "
                        f"local Ollama/GHA Gemini pipeline for store={store}."
                    )
                elif has_existing_text:
                    for k in text_keys:
                        if existing.get(k):
                            payload[k] = existing[k]
                    age_label = f"{age_days:.1f}d" if age_days is not None else "unknown age"
                    print(
                        f"[weekly-insights] preserved existing commentary for store={store} "
                        f"(keys={[k for k in text_keys if existing.get(k)]}, age={age_label})",
                        file=sys.stderr,
                    )

        store_dir = base_dir / store
        _ensure_dir(store_dir)
        out_path = store_dir / f"{date_label}.json"
        with out_path.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=True, indent=2)
            handle.write("\n")

        if sync_to_supabase:
            _upsert_weekly_report_to_supabase(
                store=store,
                date_label=date_label,
                generated_at=generated_at,
                payload=payload,
            )

    # 全店処理後、keep_alive="10m" で常駐させていたモデルをアンロードし GPU を音楽PJ等へ返す。
    # (Request/urlopen は未 import のためここで自己完結して呼ぶ。best-effort)
    try:
        import urllib.request as _u
        _u.urlopen(_u.Request(
            "http://localhost:11434/api/generate",
            data=json.dumps({"model": "gemma4:e4b", "keep_alive": 0, "prompt": ""}).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        ), timeout=30).read()
    except Exception:  # noqa: BLE001
        pass

    # index.json は退役済み（2026-07-18 index.json retirement）。args.skip_index は
    # ここでは一切参照しない (generate-weekly-insights.yml との後方互換のため
    # argparse には残す no-op)。
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
