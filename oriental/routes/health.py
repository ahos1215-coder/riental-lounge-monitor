from __future__ import annotations

from flask import Blueprint, current_app, jsonify

from ..config import AppConfig

bp = Blueprint("health", __name__)


def _config() -> AppConfig:
    return current_app.config["APP_CONFIG"]


@bp.get("/healthz")
def healthz():
    cfg = _config()
    return jsonify({"ok": True, **cfg.health_summary()})