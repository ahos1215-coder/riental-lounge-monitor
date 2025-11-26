from __future__ import annotations

import os
from flask import Blueprint, current_app, jsonify, request

from ..config import AppConfig
from ..ml.forecast_service import ForecastService

bp = Blueprint("forecast", __name__, url_prefix="/api")


def _service() -> ForecastService:
    if "FORECAST_SERVICE" not in current_app.config:
        current_app.config["FORECAST_SERVICE"] = ForecastService.from_app(current_app)
    return current_app.config["FORECAST_SERVICE"]


def _guard():
    if os.getenv("ENABLE_FORECAST", "0") != "1":
        return jsonify({"ok": False, "error": "forecast-disabled"}), 503
    return None


def _config() -> AppConfig:
    return current_app.config["APP_CONFIG"]


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

    current_app.logger.info("api_forecast.start store=%s horizon=next_hour", store)
    raw = _service().forecast_next_hour(store_id=store, freq_min=freq)
    if not raw.get("ok", True):
        current_app.logger.warning("api_forecast.error store=%s detail=%s", store, raw.get("detail"))
        return jsonify(raw)
    points = _normalize_points(raw)
    current_app.logger.info(
        "api_forecast.success store=%s points=%d", store, len(points)
    )

    # 必要最低限だけ返す（ok + data）
    return jsonify({"ok": True, "data": points})


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

    current_app.logger.info("api_forecast.start store=%s horizon=today", store)
    raw = _service().forecast_today(
        store_id=store, freq_min=freq, start_h=start_h, end_h=end_h
    )
    if not raw.get("ok", True):
        current_app.logger.warning("api_forecast.error store=%s detail=%s", store, raw.get("detail"))
        return jsonify(raw)
    points = _normalize_points(raw)
    current_app.logger.info(
        "api_forecast.success store=%s points=%d", store, len(points)
    )

    # ここも ok + data で統一
    return jsonify({"ok": True, "data": points})
