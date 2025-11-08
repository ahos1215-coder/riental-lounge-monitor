from __future__ import annotations

from pathlib import Path

from flask import Flask, jsonify
from pydantic import ValidationError

from .clients.gas_client import GasClient
from .clients.http import ConfiguredSession
from .config import AppConfig
from .routes import data, health, tasks
from .utils import storage
from .utils.log import setup_logging


def create_app(config: AppConfig | None = None) -> Flask:
    cfg = config or AppConfig.from_env()
    template_folder = Path(__file__).with_name("templates")

    app = Flask(
        __name__,
        template_folder=str(template_folder),
    )
    app.url_map.strict_slashes = False
    app.config["APP_CONFIG"] = cfg

    session = ConfiguredSession(
        timeout=cfg.http_timeout,
        retries=cfg.http_retry,
        user_agent=cfg.user_agent,
    )
    gas_client = GasClient(session=session, webhook_url=cfg.gs_webhook_url, read_url=cfg.gs_read_url)
    app.config["HTTP_SESSION"] = session
    app.config["GAS_CLIENT"] = gas_client

    logger = setup_logging(cfg.log_level)
    app.logger.handlers = logger.handlers
    app.logger.setLevel(logger.level)

    storage.ensure_data_dir(cfg)

    app.register_blueprint(health.bp)
    app.register_blueprint(data.bp)
    app.register_blueprint(tasks.bp)

    @app.errorhandler(ValidationError)
    def _handle_validation_error(err: ValidationError):  # type: ignore[override]
        return jsonify({"ok": False, "errors": err.errors()}), 400

    return app