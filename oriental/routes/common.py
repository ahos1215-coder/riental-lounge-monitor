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
    """Resolve `store` / `store_id` query param to an internal store identifier.

    Lenient: an unknown slug silently falls back to cfg.store_id. This is the
    right behaviour for endpoints where "unresolved -> use configured default"
    is legitimate (/api/forecast_*, /api/second_venues). Do NOT use this for
    single-store data endpoints where an unknown/closed slug must not quietly
    return a different store's data — use resolve_store_id_strict() there.
    """
    from ..utils.stores import resolve_store_identifier

    store_arg = request.args.get("store_id") or request.args.get("store")
    store_id, _ = resolve_store_identifier(store_arg, cfg.store_id)
    return store_id


def resolve_store_id_strict(cfg: AppConfig) -> tuple[str, str] | None:
    """Resolve `store` / `store_id` query param, requiring an exact match
    against a known store slug/id when one is supplied.

    - No `store`/`store_id` query param at all -> falls back to cfg.store_id
      (preserves the historical single-store default behaviour for callers
      that omit the param entirely).
    - An unknown or closed-store slug (e.g. a removed store like sapporo_ag,
      or a nonexistent slug) -> returns None so the caller can respond with a
      clear 404 instead of silently serving cfg.store_id's data under an
      unrelated slug (bug #5, 2026-07 Fable audit).

    Returns (store_id, slug) on success.
    """
    from ..utils.stores import resolve_store_identifier_strict

    store_arg = request.args.get("store_id") or request.args.get("store")
    if not store_arg:
        default_id = cfg.store_id
        return default_id, default_id.split("ol_", 1)[-1]
    return resolve_store_identifier_strict(store_arg)
