"""運用アラート Webhook 送信の共有ヘルパー（stdlib のみ）。

`OPS_NOTIFY_WEBHOOK_URL` へ best-effort で POST する。未設定なら no-op。
送信失敗しても例外は投げない（呼び出し元の本処理を止めないため）。

**payload の形式は `OPS_NOTIFY_WEBHOOK_TYPE` で切り替える**（`discord` なら
`{"content": ...}`、未設定・`slack` なら `{"text": ...}`）。
.github/workflows/notify-on-failure.yml は元から両対応だったのに、Python 側の
2箇所（score_forecasts の精度劣化アラート / generate_weekly_insights の週報失敗
通知）は Slack 形式固定だったため、オーナーが Discord を選ぶと Python 側の通知
だけが 400 で静かに落ちる状態だった。仕様の正本を1箇所にしてこれを解消する。
対応する値は plan/ENV.md の `OPS_NOTIFY_WEBHOOK_TYPE` を参照。

scripts/_supabase_common.py と同じ規約で、呼び出し側が
`sys.path.insert(0, <自分のディレクトリ>)` した上でベアインポートする。
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from typing import TextIO


def build_payload(message: str) -> dict[str, str]:
    """Webhook の種類に応じた payload。.github/workflows/notify-on-failure.yml と同じ判定。"""
    kind = (os.environ.get("OPS_NOTIFY_WEBHOOK_TYPE") or "slack").strip().lower()
    key = "content" if kind == "discord" else "text"
    return {key: message}


def notify_ops(
    message: str,
    *,
    prefix: str,
    stream: TextIO | None = None,
    fail_label: str = "failed",
    detail_limit: int = 150,
) -> None:
    """アラートを送る。`prefix` はログ行の接頭辞（例: "[score][alert]"）。

    `stream` / `fail_label` / `detail_limit` は、移行前の呼び出し元2箇所の
    ログ出力（stdout か stderr か・失敗行の文言・例外文字列の切り詰め長）を
    そのまま維持するためのもの。
    """
    out = stream if stream is not None else sys.stdout
    url = (os.environ.get("OPS_NOTIFY_WEBHOOK_URL") or "").strip()
    if not url:
        print(f"{prefix} (OPS_NOTIFY_WEBHOOK_URL unset) {message}", file=out)
        return
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(build_payload(message)).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15):
            pass
        print(f"{prefix} sent: {message}", file=out)
    except Exception as exc:  # noqa: BLE001
        print(f"{prefix} {fail_label}: {str(exc)[:detail_limit]}", file=out)
