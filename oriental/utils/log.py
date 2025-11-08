from __future__ import annotations

import json
import logging
from typing import Any

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s :: %(message)s"
_SENSITIVE_KEYS = ("token", "secret", "key", "signature")
_MAX_PAYLOAD_LEN = 1000


def setup_logging(level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger("oriental")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        logger.addHandler(handler)
    numeric_level = logging.getLevelName(level.upper())
    logger.setLevel(numeric_level)
    logger.propagate = False
    return logger


def format_payload(payload: Any, *, limit: int = _MAX_PAYLOAD_LEN) -> str:
    """Serialize payload safely for logs, masking secrets and truncating long lines."""
    masked = _mask_sensitive(payload)
    try:
        text = json.dumps(masked, ensure_ascii=False, sort_keys=True, default=str)
    except TypeError:
        text = str(masked)
    return _truncate(text, limit)


def _mask_sensitive(payload: Any):
    if isinstance(payload, dict):
        masked: dict[Any, Any] = {}
        for key, value in payload.items():
            if any(marker in str(key).lower() for marker in _SENSITIVE_KEYS):
                masked[key] = "***"
            else:
                masked[key] = _mask_sensitive(value)
        return masked
    if isinstance(payload, list):
        return [_mask_sensitive(item) for item in payload]
    if isinstance(payload, tuple):
        return tuple(_mask_sensitive(item) for item in payload)
    return payload


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"
