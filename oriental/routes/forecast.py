from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Blueprint, current_app, jsonify, request

# Flask プロセス内でのキャッシュ TTL（秒）
# ワーカーごとに独立するが、CDN キャッシュと合わせて十分な効果がある
_FORECAST_CACHE_TTL = int(os.getenv("FORECAST_RESULT_CACHE_TTL", "60"))  # 1 分

from ..config import AppConfig
from ..ml.forecast_service import ForecastService
from ..ml.megribi_score import megribi_score as calc_megribi_score

bp = Blueprint("forecast", __name__, url_prefix="/api")


def _service() -> ForecastService:
    if "FORECAST_SERVICE" not in current_app.config:
        current_app.config["FORECAST_SERVICE"] = ForecastService.from_app(current_app)
    return current_app.config["FORECAST_SERVICE"]


def _guard():
    if not _config().enable_forecast:
        return jsonify({"ok": False, "error": "forecast-disabled"}), 503
    return None


def _config() -> AppConfig:
    return current_app.config["APP_CONFIG"]


def _error_status(raw: dict) -> int:
    err = raw.get("error")
    if err in {"model_schema_mismatch", "model_unavailable"}:
        return 503
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


def _supabase_provider(cfg: AppConfig):
    from ..data.provider import SupabaseLogsProvider
    if not (cfg.supabase_url and cfg.supabase_service_role_key):
        return None
    if "SUPABASE_PROVIDER" not in current_app.config:
        current_app.config["SUPABASE_PROVIDER"] = SupabaseLogsProvider(
            base_url=cfg.supabase_url,
            api_key=cfg.supabase_service_role_key,
            session=current_app.config.get("HTTP_SESSION"),
            logger=current_app.logger,
        )
    return current_app.config["SUPABASE_PROVIDER"]


def _resolve_store_id(cfg: AppConfig) -> str:
    from ..utils.stores import resolve_store_identifier

    store_arg = request.args.get("store_id") or request.args.get("store")
    store_id, _ = resolve_store_identifier(store_arg, cfg.store_id)
    return store_id


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

    result = {"ok": True, "data": points, "reasoning": raw.get("reasoning", {})}
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

    result = {"ok": True, "data": points, "reasoning": raw.get("reasoning", {})}
    _set_cached(cache_key, result)
    return jsonify(result)


@bp.get("/megribi_score")
def api_megribi_score():
    """各店舗の最新データから megribi_score を計算して返す。
    ?store=slug または ?stores=slug1,slug2 で対象指定。
    省略時は全店舗を返す。
    """
    from ..utils.stores import SLUG_TO_ID

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

    valid_slugs = [(s, SLUG_TO_ID[s]) for s in slugs[:40] if s in SLUG_TO_ID]

    def _fetch_one(slug: str, store_id: str):
        rows = provider.fetch_range(store_id=store_id, limit=1)
        if not rows:
            return None
        latest = rows[-1]
        total = float(latest.get("total", 0) or 0)
        men = float(latest.get("men", 0) or 0)
        women = float(latest.get("women", 0) or 0)
        capacity = 80.0
        occupancy_rate = min(total / capacity, 1.0) if capacity > 0 else 0.0
        female_ratio = women / total if total > 0 else 0.5
        score = calc_megribi_score(
            female_ratio=female_ratio,
            occupancy_rate=occupancy_rate,
        )
        return {
            "slug": slug,
            "score": round(score, 3),
            "total": int(total),
            "men": int(men),
            "women": int(women),
            "female_ratio": round(female_ratio, 3),
            "occupancy_rate": round(occupancy_rate, 3),
            "ts": latest.get("ts", ""),
        }

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
