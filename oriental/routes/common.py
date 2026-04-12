"""Shared helpers for Flask route modules.

`_config()`, `_supabase_provider()`, `_resolve_store_id()` が 4 ファイルに
重複していたため、ここに集約する。
"""

from __future__ import annotations

from flask import current_app, request

from ..config import AppConfig
from ..data.provider import SupabaseLogsProvider


def get_config() -> AppConfig:
    """Return the application config from the Flask app context."""
    return current_app.config["APP_CONFIG"]


def get_supabase_provider(cfg: AppConfig) -> SupabaseLogsProvider | None:
    """Return a cached SupabaseLogsProvider, or None if not configured."""
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


def resolve_store_id(cfg: AppConfig) -> str:
    """Resolve `store` / `store_id` query param to an internal store identifier."""
    from ..utils.stores import resolve_store_identifier

    store_arg = request.args.get("store_id") or request.args.get("store")
    store_id, _ = resolve_store_identifier(store_arg, cfg.store_id)
    return store_id
