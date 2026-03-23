from __future__ import annotations

from flask import Blueprint, current_app, jsonify

from ..config import AppConfig

bp = Blueprint("health", __name__)


def _config() -> AppConfig:
    return current_app.config["APP_CONFIG"]


@bp.get("/healthz")
def healthz():
    cfg = _config()
    payload = {"ok": True, **cfg.health_summary()}
    payload["forecast_model"] = _forecast_model_status()
    return jsonify(payload)


def _forecast_model_status() -> dict:
    service = current_app.config.get("FORECAST_SERVICE")
    if service is None or getattr(service, "model_registry", None) is None:
        return {
            "loaded": False,
            "schema_version": None,
            "trained_at": None,
            "loaded_at_unix": None,
            "age_sec": None,
            "note": "forecast_service_not_initialized",
        }
    return service.model_registry.current_status()