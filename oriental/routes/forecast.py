from __future__ import annotations

import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Blueprint, current_app, jsonify, request

# Flask プロセス内でのキャッシュ TTL（秒）
# ワーカーごとに独立するが、CDN キャッシュと合わせて十分な効果がある。
# 実測データは5分おきにしか更新されないため、60秒は過剰に短く不要な再計算を招いていた
# → 180秒に緩和（2026-07）。キャッシュキー/失効ロジックは変更なし。
_FORECAST_CACHE_TTL = int(os.getenv("FORECAST_RESULT_CACHE_TTL", "180"))  # 3 分

from ..config import AppConfig
from ..ml.forecast_service import ForecastService
from ..ml.megribi_score import megribi_score as calc_megribi_score
from ..utils.stores import SLUG_TO_ID
from .common import get_config as _config, get_supabase_provider, resolve_store_id

bp = Blueprint("forecast", __name__, url_prefix="/api")

# マルチストア系エンドポイントの上限。既知の全店舗数（44店舗）を下回らないようにする。
# DoS 対策は SLUG_TO_ID による既知 slug のみのフィルタリングとレート制限で担保する。
MAX_MULTI_STORES = len(SLUG_TO_ID)

# /api/forecast_snapshot の date パラメータ（夜の JST 日付）。YYYYMMDD の8桁固定。
_NIGHT_DATE_RE = re.compile(r"^\d{8}$")


def _service() -> ForecastService:
    if "FORECAST_SERVICE" not in current_app.config:
        current_app.config["FORECAST_SERVICE"] = ForecastService.from_app(current_app)
    return current_app.config["FORECAST_SERVICE"]


def _guard():
    if not _config().enable_forecast:
        return jsonify({"ok": False, "error": "forecast-disabled"}), 503
    return None


def _error_status(raw: dict) -> int:
    err = raw.get("error")
    if err in {"model_schema_mismatch", "model_unavailable"}:
        return 503
    # 予期せぬ内部エラーは 5xx にして監視・フロントが「予測利用不可」を検知できるようにする
    if err == "forecast_internal_error":
        return 500
    return 200


# ---------- 軽量な in-process キャッシュ ----------

def _forecast_cache() -> dict:
    if "FORECAST_RESULT_CACHE" not in current_app.config:
        current_app.config["FORECAST_RESULT_CACHE"] = {}
    return current_app.config["FORECAST_RESULT_CACHE"]


def _get_cached(key: str) -> dict | None:
    cache = _forecast_cache()
    entry = cache.get(key)
    if not entry:
        return None
    if time.time() - entry["at"] > _FORECAST_CACHE_TTL:
        cache.pop(key, None)
        return None
    return entry["data"]


def _set_cached(key: str, data: dict) -> None:
    _forecast_cache()[key] = {"at": time.time(), "data": data}


_supabase_provider = get_supabase_provider
_resolve_store_id = resolve_store_id


def _normalize_points(result: dict) -> list[dict]:
    """
    どんな結果が来ても、
    - data は「配列 list」
    - 各要素は ts を持つ dict
    という形にそろえる。
    """
    if not isinstance(result, dict):
        current_app.logger.warning(
            "api_forecast.result_not_dict -> normalize_to_empty_list"
        )
        return []

    data = result.get("data")

    if isinstance(data, list):
        filtered = [d for d in data if isinstance(d, dict) and "ts" in d]
        if len(filtered) != len(data):
            current_app.logger.warning(
                "api_forecast.data_list_had_invalid_entries -> filtered=%d -> %d",
                len(data),
                len(filtered),
            )
        return filtered

    # data が {} や None, 数値など → 空配列にする
    current_app.logger.warning(
        "api_forecast.data_not_list -> normalize_to_empty_list type=%s",
        type(data),
    )
    return []


@bp.get("/forecast_next_hour")
def forecast_next_hour():
    guard = _guard()
    if guard:
        return guard

    cfg = _config()
    store = _resolve_store_id(cfg)
    freq = max(1, int(os.getenv("FORECAST_FREQ_MIN", "15")))

    cache_key = f"next_hour:{store}"
    cached = _get_cached(cache_key)
    if cached:
        current_app.logger.info("api_forecast.cache_hit store=%s horizon=next_hour", store)
        return jsonify(cached)

    current_app.logger.info("api_forecast.start store=%s horizon=next_hour", store)
    raw = _service().forecast_next_hour(store_id=store, freq_min=freq)
    if not raw.get("ok", True):
        current_app.logger.warning("api_forecast.error store=%s detail=%s", store, raw.get("detail"))
        return jsonify(raw), _error_status(raw)
    points = _normalize_points(raw)
    current_app.logger.info(
        "api_forecast.success store=%s points=%d", store, len(points)
    )

    result = {
        "ok": True,
        "data": points,
        "reasoning": raw.get("reasoning", {}),
        "insufficient_history": bool(raw.get("insufficient_history", False)),
    }
    _set_cached(cache_key, result)
    return jsonify(result)


@bp.get("/forecast_today")
def forecast_today():
    guard = _guard()
    if guard:
        return guard

    cfg = _config()
    store = _resolve_store_id(cfg)
    freq = max(1, int(os.getenv("FORECAST_FREQ_MIN", "15")))

    start_h = int(os.getenv("NIGHT_START_H", "19"))
    end_h = int(os.getenv("NIGHT_END_H", "5"))

    cache_key = f"today:{store}"
    cached = _get_cached(cache_key)
    if cached:
        current_app.logger.info("api_forecast.cache_hit store=%s horizon=today", store)
        return jsonify(cached)

    current_app.logger.info("api_forecast.start store=%s horizon=today", store)
    raw = _service().forecast_today(
        store_id=store, freq_min=freq, start_h=start_h, end_h=end_h
    )
    if not raw.get("ok", True):
        current_app.logger.warning("api_forecast.error store=%s detail=%s", store, raw.get("detail"))
        return jsonify(raw), _error_status(raw)
    points = _normalize_points(raw)
    current_app.logger.info(
        "api_forecast.success store=%s points=%d", store, len(points)
    )

    result = {
        "ok": True,
        "data": points,
        "reasoning": raw.get("reasoning", {}),
        "insufficient_history": bool(raw.get("insufficient_history", False)),
    }
    _set_cached(cache_key, result)
    return jsonify(result)


@bp.get("/forecast_today_multi")
def forecast_today_multi():
    """複数店舗の forecast_today を1リクエストで返す。
    ?stores=slug1,slug2,... で最大 MAX_MULTI_STORES 店舗（既知の全店舗数）。
    ThreadPoolExecutor で並列実行 — 12店舗でも ~1-2s。
    """
    guard = _guard()
    if guard:
        return guard

    cfg = _config()
    logger = current_app.logger

    raw_stores = request.args.get("stores") or ""
    slugs = [s.strip().lower() for s in raw_stores.split(",") if s.strip()]
    valid = [(s, SLUG_TO_ID[s]) for s in slugs if s in SLUG_TO_ID][:MAX_MULTI_STORES]

    if not valid:
        return jsonify({"ok": False, "error": "no-valid-stores"}), 422

    freq = max(1, int(os.getenv("FORECAST_FREQ_MIN", "15")))
    start_h = int(os.getenv("NIGHT_START_H", "19"))
    end_h = int(os.getenv("NIGHT_END_H", "5"))

    # Flask コンテキスト外のスレッドで使えるよう、参照を先に取得
    service = _service()
    cache = _forecast_cache()

    def _fetch_one(slug: str, store_id: str):
        cache_key = f"today:{store_id}"
        entry = cache.get(cache_key)
        if entry and time.time() - entry["at"] <= _FORECAST_CACHE_TTL:
            return slug, entry["data"]

        raw = service.forecast_today(
            store_id=store_id, freq_min=freq, start_h=start_h, end_h=end_h
        )
        if not raw.get("ok", True):
            return slug, {"ok": False, "data": [], "error": raw.get("error") or "forecast_failed"}

        data = raw.get("data")
        points = [d for d in data if isinstance(d, dict) and "ts" in d] if isinstance(data, list) else []
        result = {"ok": True, "data": points}
        cache[cache_key] = {"at": time.time(), "data": result}
        return slug, result

    by_slug: dict = {}
    errors_by_slug: dict = {}
    with ThreadPoolExecutor(max_workers=min(12, len(valid))) as pool:
        futures = {pool.submit(_fetch_one, s, sid): s for s, sid in valid}
        for fut in as_completed(futures):
            try:
                slug_key, data = fut.result()
                by_slug[slug_key] = data
            except Exception as exc:
                slug_key = futures[fut]
                by_slug[slug_key] = {"ok": False, "data": [], "error": str(exc)}

    # 個別店舗の失敗を可視化する（全体は ok:true / 200 のまま、追加フィールドのみ）
    for slug_key, entry in by_slug.items():
        if isinstance(entry, dict) and not entry.get("ok", True):
            errors_by_slug[slug_key] = entry.get("error") or "unknown_error"

    logger.info(
        "api_forecast_today_multi.success count=%d partial_failure_count=%d",
        len(by_slug),
        len(errors_by_slug),
    )
    return jsonify({
        "ok": True,
        "by_slug": by_slug,
        "partial_failure_count": len(errors_by_slug),
        "errors_by_slug": errors_by_slug,
    })


@bp.get("/megribi_score")
def api_megribi_score():
    """各店舗の最新データから megribi_score を計算して返す。
    ?store=slug または ?stores=slug1,slug2 で対象指定。
    省略時は全店舗を返す。
    """
    from ..utils.stores import AISEKIYA_TOTAL_CAPACITY, SLUG_TO_ID

    cfg = _config()
    logger = current_app.logger

    single = request.args.get("store")
    multi = request.args.get("stores")

    if single:
        slugs = [single.strip().lower()]
    elif multi:
        slugs = [s.strip().lower() for s in multi.split(",") if s.strip()]
    else:
        slugs = list(SLUG_TO_ID.keys())

    backend = (cfg.data_backend or "legacy").lower()
    if backend != "supabase" or not (cfg.supabase_url and cfg.supabase_service_role_key):
        return jsonify({"ok": False, "error": "supabase-required"}), 501

    provider = _supabase_provider(cfg)
    if provider is None:
        return jsonify({"ok": False, "error": "supabase-unavailable"}), 502

    valid_slugs = [(s, SLUG_TO_ID[s]) for s in slugs[:MAX_MULTI_STORES] if s in SLUG_TO_ID]

    def _fetch_one(slug: str, store_id: str):
        rows = provider.fetch_range(store_id=store_id, limit=1)
        if not rows:
            return None
        latest = rows[-1]
        total = float(latest.get("total", 0) or 0)
        men = float(latest.get("men", 0) or 0)
        women = float(latest.get("women", 0) or 0)
        is_aisekiya = store_id.startswith("ay_")
        if is_aisekiya:
            capacity = float(AISEKIYA_TOTAL_CAPACITY.get(store_id, 80.0))
        else:
            capacity = 80.0
        occupancy_rate = min(total / capacity, 1.0) if capacity > 0 else 0.0
        female_ratio = women / total if total > 0 else 0.5
        score = calc_megribi_score(
            female_ratio=female_ratio,
            occupancy_rate=occupancy_rate,
        )

        item = {
            "slug": slug,
            "score": round(score, 3),
            "total": int(total),
            "men": int(men),
            "women": int(women),
            "female_ratio": round(female_ratio, 3),
            "occupancy_rate": round(occupancy_rate, 3),
            "ts": latest.get("ts", ""),
            "men_seat_pct": None,
            "women_seat_pct": None,
        }
        if is_aisekiya:
            # 相席屋 (ay_*) は %表示のみが正式仕様。生の推定人数はフロントに渡さず、
            # 席の埋まり具合(%)をサーバー側で計算して渡す
            # （home-client.tsx の seatFullnessPercent(count, perGenderCapacity) と同じ換算）。
            per_gender_capacity = capacity / 2 if capacity > 0 else 0.0
            if per_gender_capacity > 0:
                item["men_seat_pct"] = round(min(1.0, men / per_gender_capacity) * 100)
                item["women_seat_pct"] = round(min(1.0, women / per_gender_capacity) * 100)
            item["men"] = None
            item["women"] = None
            item["total"] = None
        return item

    results = []
    with ThreadPoolExecutor(max_workers=min(12, len(valid_slugs) or 1)) as pool:
        futures = {pool.submit(_fetch_one, s, sid): s for s, sid in valid_slugs}
        for fut in as_completed(futures):
            try:
                item = fut.result()
                if item:
                    results.append(item)
            except Exception:
                pass

    results.sort(key=lambda r: r["score"], reverse=True)
    logger.info("api_megribi_score.success count=%d", len(results))
    return jsonify({"ok": True, "data": results})


def _storage_get(cfg: AppConfig, path: str) -> bytes | None:
    """Supabase Storage から生バイト列を取得する共通ヘルパー。

    `_fetch_live_accuracy`（/api/forecast_accuracy）と `_fetch_forecast_snapshot`
    （/api/forecast_snapshot）の両方から使う。オブジェクトが存在しない場合
    （404、または Supabase が返す 400 の "not found" 系エラー）は None を返し、
    それ以外の HTTP エラーは呼び出し側に伝播させる（呼び出し側で握りつぶす）。
    """
    import urllib.error
    import urllib.request

    supabase_url = (cfg.supabase_url or "").rstrip("/")
    key = cfg.supabase_service_role_key or ""
    bucket = cfg.forecast_model_bucket or "ml-models"
    if not supabase_url or not key:
        return None

    endpoint = f"{supabase_url}/storage/v1/object/{bucket}/{path}"
    req = urllib.request.Request(
        endpoint, headers={"apikey": key, "Authorization": f"Bearer {key}"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        if exc.code == 400:
            try:
                body = exc.read().decode("utf-8", "replace").lower()
            except Exception:  # noqa: BLE001
                body = ""
            if "not_found" in body or "not found" in body or "object not found" in body:
                return None
        raise


def _fetch_live_accuracy(cfg: AppConfig) -> dict | None:
    """Supabase Storage の答え合わせ結果 (scripts/score_forecasts.py が毎晩書き込む)
    から実測精度を組み立てる。summary.json が無い/壊れている、または nights が
    空なら None を返す（呼び出し側は holdout の metrics にフォールバックする）。
    Storage 障害でエンドポイント全体を落とさないよう、例外はすべてここで握りつぶす。
    """
    import json

    try:
        raw = _storage_get(cfg, "accuracy/scores/summary.json")
        if raw is None:
            return None
        summary = json.loads(raw.decode())
        nights = summary.get("nights")
        if not isinstance(nights, list) or not nights:
            return None

        def _avg(key_name: str, n: int) -> float | None:
            vals = [
                x.get(key_name) for x in nights[:n]
                if isinstance(x.get(key_name), (int, float))
            ]
            return round(sum(vals) / len(vals), 2) if vals else None

        # mae_30d は「本当に30夜以上」蓄積されるまで null にする。7夜しか無いのに
        # mae_7d と同値を「30日平均」と称するのは不誠実なラベルになるため。
        # フロントは nights_count と合わせて「n=X夜」表示にフォールバックする。
        n_nights = len(nights)
        live: dict = {
            "mae_7d": _avg("overall_live_mae", 7),
            "mae_30d": _avg("overall_live_mae", 30) if n_nights >= 30 else None,
            "baseline_7d": _avg("overall_baseline_mae", 7),
            "nights_count": n_nights,
            "updated_at": summary.get("updated_at_utc"),
            "stores_scored_latest": nights[0].get("stores_scored"),
            "per_store": {},
        }

        latest_date = nights[0].get("night_date")
        if latest_date:
            daily_raw = _storage_get(cfg, f"accuracy/scores/{latest_date}.json")
            if daily_raw is not None:
                daily = json.loads(daily_raw.decode())
                per_store = daily.get("per_store")
                if isinstance(per_store, dict):
                    live["per_store"] = per_store

        return live
    except Exception:  # noqa: BLE001
        # Storage 障害・パース失敗は「実測精度なし」として holdout にフォールバックさせる
        current_app.logger.warning("api_forecast_accuracy.live_fetch_failed", exc_info=True)
        return None


def _fetch_forecast_snapshot(cfg: AppConfig, date: str) -> dict | None:
    """その夜（JST, YYYYMMDD）に実際に配信されていた予測のスナップショットを読み込む。

    scripts/snapshot_forecasts.py が毎晩 ~18:10 JST（夜が始まる前）に
    `<bucket>/accuracy/snapshots/<date>.json` として保存したものをそのまま返す。
    ファイルが無い（まだ書き込まれていない新しい夜 / この機能導入前の古い夜）、
    または壊れている場合は None を返す（呼び出し側は ok:false として扱い、
    実測グラフのみ表示にフォールバックする＝エラーではない）。
    """
    import json

    try:
        raw = _storage_get(cfg, f"accuracy/snapshots/{date}.json")
        if raw is None:
            return None
        return json.loads(raw.decode())
    except Exception:  # noqa: BLE001
        current_app.logger.warning(
            "api_forecast_snapshot.fetch_failed date=%s", date, exc_info=True
        )
        return None


@bp.get("/forecast_accuracy")
def api_forecast_accuracy():
    """Return per-store accuracy: 学習時の holdout metrics（後方互換）に加え、
    Supabase Storage に蓄積された本番の答え合わせ結果（live）を返す。
    """
    import json
    from pathlib import Path

    cfg = _config()
    cache_dir = Path(cfg.forecast_model_cache_dir)
    metadata_path = cache_dir / "metadata.json"

    if not metadata_path.exists():
        return jsonify({"ok": False, "error": "metadata-not-found"}), 404

    try:
        meta = json.loads(metadata_path.read_text(encoding="utf-8"))
    except Exception:
        return jsonify({"ok": False, "error": "metadata-parse-error"}), 500

    metrics = meta.get("metrics")
    if not metrics:
        return jsonify({"ok": False, "error": "no-metrics-in-metadata"}), 404

    live = _fetch_live_accuracy(cfg)

    return jsonify({
        "ok": True,
        "trained_at": meta.get("trained_at"),
        "metrics": metrics,
        "live": live,
    })


@bp.get("/forecast_snapshot")
def api_forecast_snapshot():
    """完了済みの夜（昨日・先週・カスタムの過去日、または今日モードで既に夜が
    終わっている場合）に「実際にその夜配信されていた予測」を返す、答え合わせ用
    オーバーレイ。/api/forecast_today は常に "これからの夜" しか返さないため、
    終わった夜の予測を後から見るにはこのスナップショット（毎晩 ~18:10 JST に
    scripts/snapshot_forecasts.py が保存）を読むしかない。

    ?store=<slug>&date=<YYYYMMDD> （date は対象の夜の JST 開始日＝19:00 側の日付）。

    スナップショットが無い（対象の夜がまだ新しすぎる/この機能導入前で記録が無い）
    場合は ok:false・HTTP 200 を返す（エラーではなく「無いのが正常」なケース）。
    store/date が不正な場合のみ 400。
    """
    cfg = _config()

    store = (request.args.get("store") or "").strip().lower()
    date = (request.args.get("date") or "").strip()

    if store not in SLUG_TO_ID:
        return jsonify({"ok": False, "error": "invalid-store"}), 400
    if not _NIGHT_DATE_RE.match(date):
        return jsonify({"ok": False, "error": "invalid-date"}), 400

    snapshot = _fetch_forecast_snapshot(cfg, date)
    by_slug = snapshot.get("by_slug") if isinstance(snapshot, dict) else None
    data = by_slug.get(store) if isinstance(by_slug, dict) else None

    if not isinstance(data, list):
        current_app.logger.info(
            "api_forecast_snapshot.missing store=%s date=%s", store, date
        )
        resp = jsonify({"ok": False, "date": date, "data": []})
    else:
        current_app.logger.info(
            "api_forecast_snapshot.success store=%s date=%s points=%d",
            store, date, len(data),
        )
        resp = jsonify({"ok": True, "date": date, "data": data})

    # 過去の夜のスナップショットは不変（もう書き換わらない）→ 長め CDN キャッシュ。
    # ok:false（未記録）も含め、同じ date は将来も同じ結果になるため一緒に長くキャッシュしてよい。
    resp.headers["Cache-Control"] = "public, s-maxage=86400, stale-while-revalidate=604800"
    return resp
