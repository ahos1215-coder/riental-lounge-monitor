from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

# リポジトリルートの .env / .env.local を読み込む（Next 用の .env.local に SUPABASE_* を置ける）
# 順序: 先に .env、次に .env.local で上書き（ローカル秘密を優先）
try:
    _root = Path(__file__).resolve().parent.parent
    _env_base = _root / ".env"
    _env_local = _root / ".env.local"
    if _env_base.is_file():
        load_dotenv(_env_base, override=False)
    if _env_local.is_file():
        load_dotenv(_env_local, override=True)
except Exception as exc:  # pragma: no cover
    print(f"[config] failed to load .env / .env.local: {exc}")


@dataclass(slots=True)
class AppConfig:
    """Centralised configuration loaded from the environment."""

    target_url: str
    store_name: str
    store_id: str
    window_start: int
    window_end: int
    timezone: str
    gs_webhook_url: str
    gs_read_url: str
    supabase_url: str
    supabase_service_role_key: str
    data_backend: str
    log_level: str
    http_timeout: float
    http_retry: int
    user_agent: str
    data_dir: Path
    data_file: Path
    log_file: Path
    max_range_limit: int  # FIX: configurable /api/range upper bound
    forecast_model_bucket: str
    forecast_model_prefix: str
    forecast_model_cache_dir: Path
    forecast_model_refresh_sec: int
    forecast_model_schema_version: str
    enable_forecast: bool

    @classmethod
    def from_env(cls) -> "AppConfig":
        data_dir = Path(os.getenv("DATA_DIR", "data"))
        window_start = _as_int(os.getenv("WINDOW_START", "19"), fallback=19)
        window_end = _as_int(os.getenv("WINDOW_END", "5"), fallback=5)
        http_timeout = float(os.getenv("HTTP_TIMEOUT_S", "12"))
        http_retry = _as_int(os.getenv("HTTP_RETRY", "3"), fallback=3)
        max_range_limit = _as_int(os.getenv("MAX_RANGE_LIMIT", "50000"), fallback=50000)  # FIX
        forecast_model_refresh_sec = _as_int(os.getenv("FORECAST_MODEL_REFRESH_SEC", "900"), fallback=900)
        enable_forecast = os.getenv("ENABLE_FORECAST", "0").strip() == "1"
        supabase_url = os.getenv("SUPABASE_URL", "")
        supabase_service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SERVICE_KEY", "")
        data_backend = os.getenv("DATA_BACKEND", "supabase").lower().strip() or "supabase"
        store_id = os.getenv("STORE_ID") or os.getenv("SUPABASE_STORE_ID") or "ol_nagasaki"
        forecast_model_cache_dir = Path(os.getenv("FORECAST_MODEL_CACHE_DIR", str(data_dir / "ml_models")))
        data_file_env = os.getenv("DATA_FILE")
        data_file = Path(data_file_env) if data_file_env else data_dir / "data.json"
        if not data_file.exists():
            fallback_plan = Path("plan") / "data.json"
            if fallback_plan.exists():
                data_file = fallback_plan
        return cls(
            target_url=os.getenv("TARGET_URL", "https://oriental-lounge.com/stores/38"),
            store_name=os.getenv("STORE_NAME", "長崎店"),
            store_id=store_id,
            window_start=window_start,
            window_end=window_end,
            timezone=os.getenv("TIMEZONE", "Asia/Tokyo"),
            gs_webhook_url=os.getenv("GS_WEBHOOK_URL", ""),
            gs_read_url=os.getenv("GS_READ_URL", ""),
            supabase_url=supabase_url,
            supabase_service_role_key=supabase_service_role_key,
            data_backend=data_backend,
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            http_timeout=http_timeout,
            http_retry=http_retry,
            user_agent=os.getenv(
                "HTTP_USER_AGENT",
                "OrientalLoungeMonitor/1.0 (+https://oriental-lounge.com)"
            ),
            data_dir=data_dir,
            data_file=data_file,
            log_file=data_dir / "log.jsonl",
            max_range_limit=max_range_limit,
            forecast_model_bucket=os.getenv("FORECAST_MODEL_BUCKET", "ml-models"),
            forecast_model_prefix=os.getenv("FORECAST_MODEL_PREFIX", "forecast/latest"),
            forecast_model_cache_dir=forecast_model_cache_dir,
            forecast_model_refresh_sec=forecast_model_refresh_sec,
            forecast_model_schema_version=os.getenv("FORECAST_MODEL_SCHEMA_VERSION", "v1"),
            enable_forecast=enable_forecast,
        )

    def health_summary(self) -> dict[str, object]:
        return {
            "store": self.store_name,
            "target": bool(self.target_url),
            "gs_webhook": bool(self.gs_webhook_url),
            "gs_read": bool(self.gs_read_url),
            "timezone": self.timezone,
            "window": {"start": self.window_start, "end": self.window_end},
            "data_backend": self.data_backend,
            "supabase": {
                "url": bool(self.supabase_url),
                "service_role": bool(self.supabase_service_role_key),
                "store_id": self.store_id,
            },
            "http_timeout": self.http_timeout,
            "http_retry": self.http_retry,
            "max_range_limit": self.max_range_limit,  # FIX
            "forecast_model": {
                "bucket": self.forecast_model_bucket,
                "prefix": self.forecast_model_prefix,
                "refresh_sec": self.forecast_model_refresh_sec,
                "schema_version": self.forecast_model_schema_version,
            },
            "forecast_enabled": self.enable_forecast,
        }

    def summary(self) -> dict[str, object]:
        """Summarise runtime config for /api/meta."""
        return {
            "store": self.store_name,
            "store_id": self.store_id,
            "data_backend": self.data_backend,
            "supabase": {
                "url": bool(self.supabase_url),
                "service_role": bool(self.supabase_service_role_key),
                "store_id": self.store_id,
            },
            "timezone": self.timezone,
            "window": {"start": self.window_start, "end": self.window_end},
            "http_timeout": self.http_timeout,
            "http_retry": self.http_retry,
            "max_range_limit": self.max_range_limit,
            "forecast_model": {
                "bucket": self.forecast_model_bucket,
                "prefix": self.forecast_model_prefix,
                "refresh_sec": self.forecast_model_refresh_sec,
                "schema_version": self.forecast_model_schema_version,
            },
            "forecast_enabled": self.enable_forecast,
        }


def _as_int(raw: str | None, *, fallback: int) -> int:
    if raw is None:
        return fallback  # FIX
    try:
        return int(raw)
    except (TypeError, ValueError):
        return fallback
