from __future__ import annotations

import os
from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify

from ..utils import timeutil
from .common import get_config as _config

bp = Blueprint("health", __name__)


@bp.get("/healthz")
def healthz():
    cfg = _config()
    payload = {"ok": True, **cfg.health_summary()}
    payload["forecast_model"] = _forecast_model_status()
    payload["data_freshness"] = _data_freshness(cfg)
    payload["memory"] = _memory_status()
    return jsonify(payload)


def _process_rss_mb() -> float | None:
    """現在プロセスの RSS を MB で返す。

    本番 Linux (Render) は `/proc/self/status` の VmRSS を読む（stdlib のみ・追加依存なし）。
    Windows 開発機ではベストエフォートで ctypes(GetProcessMemoryInfo) を試し、
    失敗・非対応環境では None を返す。/healthz は追加フィールドのみで、None でも
    `memory.rss_mb` キー自体は常に存在する（レスポンス形状は後方互換）。
    """
    # Linux 本番: /proc/self/status VmRSS（kB 表記）
    try:
        with open("/proc/self/status", "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return round(float(line.split()[1]) / 1024.0, 1)
    except (OSError, ValueError, IndexError):
        pass
    # Windows 開発機フォールバック（best-effort。失敗しても静かに None）
    try:
        import ctypes
        from ctypes import wintypes

        class _PMC(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.GetCurrentProcess.argtypes = []
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PMC), wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        c = _PMC()
        c.cb = ctypes.sizeof(_PMC)
        if psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(c), c.cb):
            return round(c.WorkingSetSize / (1024.0 * 1024.0), 1)
    except Exception:  # noqa: BLE001 — 非 Windows / 取得失敗は None にフォールバック
        pass
    return None


def _memory_status() -> dict:
    """`/healthz` 用のメモリ観測。rss_mb が MEMORY_WARN_MB(既定350) を超えたら WARNING を出す。

    Render Starter は master + 2 worker で 512MB を共有するため、worker 単体 RSS が
    350MB を超えたら OOM 再発の予兆として監視ログに残す（fix/memory-budget）。
    """
    rss_mb = _process_rss_mb()
    if rss_mb is not None:
        try:
            warn_mb = float(os.getenv("MEMORY_WARN_MB", "350"))
        except (TypeError, ValueError):
            warn_mb = 350.0
        if rss_mb > warn_mb:
            current_app.logger.warning(
                "health.memory_high rss_mb=%.1f warn_mb=%.1f", rss_mb, warn_mb
            )
    return {"rss_mb": rss_mb}


@bp.get("/readyz")
def readyz():
    """Readiness: liveness の /healthz とは異なり、実際にトラフィックを
    さばける状態かを判定する。予測モデル未ロード、または収集ウィンドウ内で
    データが stale なら 503 を返す（外部の uptime monitor 用の /healthz は
    warm-up 目的で常に 200 のまま維持する）。
    """
    cfg = _config()
    forecast_model = _forecast_model_status()
    data_freshness = _data_freshness(cfg)

    model_not_loaded = not forecast_model.get("loaded")
    data_stale = bool(data_freshness.get("stale"))
    ready = not (model_not_loaded or data_stale)

    payload = {
        "ok": ready,
        "forecast_model": forecast_model,
        "data_freshness": data_freshness,
    }
    return jsonify(payload), 200 if ready else 503


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
        # 収集は設定された時間帯（デフォルト JST 19:00-05:00）の夜間のみ稼働する。
        # 閉店時間帯は新規データが無くて当然なので stale としない（従来は毎日
        # ~14h 誤って stale=true になっていた）。tasks_tick と同じ判定ロジックを使う。
        in_window, _start_dt, _end_dt = timeutil.collection_window(
            current=timeutil.now(cfg.timezone),
            start_hour=cfg.window_start,
            end_hour=cfg.window_end,
            tz_name=cfg.timezone,
        )
        # 30 分以上更新がなければ stale（ただし収集ウィンドウ内のみ）
        stale = in_window and age_sec > 1800
        return {
            "available": True,
            "age_sec": age_sec,
            "latest_ts": latest_ts,
            "stale": stale,
            "in_collection_window": in_window,
        }
    except Exception:
        return {"available": False, "age_sec": None, "latest_ts": None, "stale": None}