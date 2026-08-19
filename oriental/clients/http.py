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
        # 【2026-08-18 障害対応】500 をリトライ対象から外した。
        # Supabase の statement timeout(57014) は HTTP 500 で返るが、これは
        # 「待てば直る一時障害」ではなく「そのクエリは何度投げても必ず失敗する」
        # 恒久エラー。旧設定では 1 リクエストにつき 4 回×timeout 12s ≒ 50 秒
        # スレッドを占有し、worker 1 × threads 8 の受け口を即座に埋め尽くして
        # DB を触らない 404 すら返せない完全停止(今夜の全停止)を招いた。
        # 429(レート制限)と 502/503/504(ゲートウェイ系の一過性)はリトライ継続。
        #
        # ★バッチ側（scripts/_retry_common.is_retryable_status）は逆に 500 も再試行する★
        # 理由（Storage の 544/500 は待てば必ず成功する／バッチは人を待たせておらず1回の
        # 失敗でその日の成果物が丸ごと欠ける）は同関数の docstring に書いてある。
        # 意図的な非対称であり、揃えるかどうかはオーナー判断。
        retry = Retry(
            total=retries,
            backoff_factor=0.6,
            status_forcelist=(429, 502, 503, 504),
            allowed_methods=("HEAD", "GET", "OPTIONS", "POST"),
        )
        adapter = requests.adapters.HTTPAdapter(max_retries=retry)
        self.mount("http://", adapter)
        self.mount("https://", adapter)
        self.headers.setdefault("User-Agent", user_agent)

    def request(self, method: str, url: str, **kwargs: Any):  # type: ignore[override]
        kwargs.setdefault("timeout", self._timeout)
        return super().request(method, url, **kwargs)