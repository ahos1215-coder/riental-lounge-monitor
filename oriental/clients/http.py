from __future__ import annotations

from typing import Any

import requests
from requests import Session
from urllib3.util.retry import Retry


class ConfiguredSession(Session):
    """Requests session with sane retry, UA, and timeout defaults."""

    def __init__(self, *, timeout: float, retries: int, user_agent: str) -> None:
        super().__init__()
        self._timeout = timeout
        retry = Retry(
            total=retries,
            backoff_factor=0.6,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("HEAD", "GET", "OPTIONS", "POST"),
        )
        adapter = requests.adapters.HTTPAdapter(max_retries=retry)
        self.mount("http://", adapter)
        self.mount("https://", adapter)
        self.headers.setdefault("User-Agent", user_agent)

    def request(self, method: str, url: str, **kwargs: Any):  # type: ignore[override]
        kwargs.setdefault("timeout", self._timeout)
        return super().request(method, url, **kwargs)