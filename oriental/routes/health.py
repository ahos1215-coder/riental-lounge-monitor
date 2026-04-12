from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify

from .common import get_config as _config

bp = Blueprint("health", __name__)


@bp.get("/healthz")
def healthz():
    cfg = _config()
    payload = {"ok": True, **cfg.health_summary()}
    payload["forecast_model"] = _forecast_model_status()
    payload["data_freshness"] = _data_freshness(cfg)
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


def _data_freshness(cfg: AppConfig) -> dict:
    """最新ログのタイムスタンプを Supabase から取得して鮮度情報を返す。
    外部監視ツールが data_freshness.stale=true を検知してアラートを上げられる。
    """
    if not cfg.supabase_url or not cfg.supabase_service_role_key:
        return {"available": False, "age_sec": None, "latest_ts": None, "stale": None}

    session = current_app.config.get("HTTP_SESSION")
    if session is None:
        return {"available": False, "age_sec": None, "latest_ts": None, "stale": None}

    endpoint = cfg.supabase_url.rstrip("/") + "/rest/v1/logs"
    headers = {
        "apikey": cfg.supabase_service_role_key,
        "Authorization": f"Bearer {cfg.supabase_service_role_key}",
        "Accept": "application/json",
    }
    params = [("select", "ts"), ("order", "ts.desc"), ("limit", "1")]

    try:
        resp = session.get(endpoint, params=params, headers=headers, timeout=5)
        if not resp.ok:
            return {"available": False, "age_sec": None, "latest_ts": None, "stale": None}
        rows = resp.json()
        if not rows:
            return {"available": True, "age_sec": None, "latest_ts": None, "stale": True}
        latest_ts = rows[0].get("ts")
        if not latest_ts:
            return {"available": True, "age_sec": None, "latest_ts": None, "stale": True}
        ts_fixed = latest_ts.replace("Z", "+00:00") if latest_ts.endswith("Z") else latest_ts
        dt = datetime.fromisoformat(ts_fixed)
        age_sec = int((datetime.now(timezone.utc) - dt).total_seconds())
        # 30 分以上更新がなければ stale
        stale = age_sec > 1800
        return {"available": True, "age_sec": age_sec, "latest_ts": latest_ts, "stale": stale}
    except Exception:
        return {"available": False, "age_sec": None, "latest_ts": None, "stale": None}