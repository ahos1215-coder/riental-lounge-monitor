from __future__ import annotations

import os
import threading
from pathlib import Path

from flask import Flask

from .clients.gas_client import GasClient
from .clients.http import ConfiguredSession
from .config import AppConfig
from .routes import data, health, tasks, forecast
from .utils import storage
from .utils.log import setup_logging


def _preload_models(app: Flask) -> None:
    """Background thread: preload all store models into memory at startup."""
    with app.app_context():
        cfg: AppConfig = app.config["APP_CONFIG"]
        if not cfg.enable_forecast:
            app.logger.info("model_preload.skip forecast_disabled")
            return
        try:
            from .ml.forecast_service import ForecastService
            from .ml.model_registry import ForecastModelRegistry

            svc = ForecastService.from_app(app)
            app.config["FORECAST_SERVICE"] = svc
            registry: ForecastModelRegistry | None = svc.model_registry
            if registry is None:
                app.logger.warning("model_preload.skip no_registry")
                return

            # 店舗マスタは utils.stores の単一ソースを使う（stores.json が読めない場合の
            # フォールバックもそちらが持つ。ここで独自に読むと二重管理になる）。
            from .utils.stores import ALL_STORE_IDS

            store_ids = list(ALL_STORE_IDS)

            loaded = 0
            for sid in store_ids:
                try:
                    registry.get_bundle(sid)
                    loaded += 1
                except Exception as exc:
                    app.logger.warning("model_preload.fail store=%s error=%s", sid, str(exc)[:80])
            app.logger.info("model_preload.done loaded=%d/%d", loaded, len(store_ids))
        except Exception as exc:
            app.logger.error("model_preload.error %s", str(exc)[:200])


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
    app.register_blueprint(forecast.bp)

    # Preload ML models in background thread (non-blocking)
    if cfg.enable_forecast and os.getenv("DISABLE_MODEL_PRELOAD") != "1":
        t = threading.Thread(target=_preload_models, args=(app,), daemon=True)
        t.start()
        app.logger.info("model_preload.started background_thread")

    return app
