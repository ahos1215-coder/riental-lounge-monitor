from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class AppConfig:
    """Centralised configuration loaded from the environment."""

    target_url: str
    store_name: str
    window_start: int
    window_end: int
    timezone: str
    gs_webhook_url: str
    gs_read_url: str
    log_level: str
    http_timeout: float
    http_retry: int
    user_agent: str
    data_dir: Path
    data_file: Path
    log_file: Path
    max_range_limit: int  # FIX: configurable /api/range upper bound

    @classmethod
    def from_env(cls) -> "AppConfig":
        data_dir = Path(os.getenv("DATA_DIR", "data"))
        window_start = _as_int(os.getenv("WINDOW_START", "19"), fallback=19)
        window_end = _as_int(os.getenv("WINDOW_END", "5"), fallback=5)
        http_timeout = float(os.getenv("HTTP_TIMEOUT_S", "12"))
        http_retry = _as_int(os.getenv("HTTP_RETRY", "3"), fallback=3)
        max_range_limit = _as_int(os.getenv("MAX_RANGE_LIMIT", "50000"), fallback=50000)  # FIX
        return cls(
            target_url=os.getenv("TARGET_URL", "https://oriental-lounge.com/stores/38"),
            store_name=os.getenv("STORE_NAME", "長崎店"),
            window_start=window_start,
            window_end=window_end,
            timezone=os.getenv("TIMEZONE", "Asia/Tokyo"),
            gs_webhook_url=os.getenv("GS_WEBHOOK_URL", ""),
            gs_read_url=os.getenv("GS_READ_URL", ""),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            http_timeout=http_timeout,
            http_retry=http_retry,
            user_agent=os.getenv(
                "HTTP_USER_AGENT",
                "OrientalLoungeMonitor/1.0 (+https://oriental-lounge.com)"
            ),
            data_dir=data_dir,
            data_file=data_dir / "data.json",
            log_file=data_dir / "log.jsonl",
            max_range_limit=max_range_limit,
        )

    def health_summary(self) -> dict[str, object]:
        return {
            "store": self.store_name,
            "target": bool(self.target_url),
            "gs_webhook": bool(self.gs_webhook_url),
            "gs_read": bool(self.gs_read_url),
            "timezone": self.timezone,
            "window": {"start": self.window_start, "end": self.window_end},
            "http_timeout": self.http_timeout,
            "http_retry": self.http_retry,
            "max_range_limit": self.max_range_limit,  # FIX
        }


def _as_int(raw: str | None, *, fallback: int) -> int:
    if raw is None:
        return fallback  # FIX
    try:
        return int(raw)
    except (TypeError, ValueError):
        return fallback
