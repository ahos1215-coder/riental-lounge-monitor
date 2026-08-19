"""運用アラート送信（scripts/_ops_notify.py）の番犬テスト。

B-03: score_forecasts.py の `_alert`（精度劣化アラート）と
generate_weekly_insights.py の `_notify_ops`（週報失敗通知）は、どちらも
OPS_NOTIFY_WEBHOOK_URL へ Slack 形式 `{"text": ...}` を固定で POST していた。
一方 .github/workflows/notify-on-failure.yml は
`vars.OPS_NOTIFY_WEBHOOK_TYPE=discord` なら `{"content": ...}` に切り替える
（plan/ENV.md でも discord を正式サポートと記載）。
つまりオーナーが Discord を選ぶと Python 側の2本だけが 400 を返され、
しかも両関数とも例外を握り潰すので「アラートが来ない」ことに気付けない。

ここでは呼び出し元2箇所の
  - URL 未設定なら HTTP リクエストを一切出さない（no-op）
  - 設定済みなら POST の宛先・Content-Type
  - ログ文言（[score][alert] / [weekly-insights][alert]）
を固定し、その上で TYPE による payload 切り替えを検証する。

ネットワークは一切使わない（urlopen をモックする）。
"""

from __future__ import annotations

import json
import urllib.request

import pytest

from scripts import generate_weekly_insights as gwi
from scripts import score_forecasts as sf


class _FakeUrlopen:
    def __init__(self, fail: Exception | None = None):
        self.reqs: list[urllib.request.Request] = []
        self.fail = fail

    def __call__(self, req, timeout=None):
        self.reqs.append(req)
        if self.fail is not None:
            raise self.fail
        return _FakeCtx()

    @property
    def payloads(self) -> list[dict]:
        return [json.loads(r.data.decode("utf-8")) for r in self.reqs]


class _FakeCtx:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return b""


@pytest.fixture
def fake_urlopen(monkeypatch: pytest.MonkeyPatch) -> _FakeUrlopen:
    fake = _FakeUrlopen()
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    # generate_weekly_insights は `from urllib.request import urlopen` なので個別に差し替える。
    monkeypatch.setattr(gwi, "urlopen", fake)
    return fake


# --------------------------------------------------------------------------- #
# 呼び出し元2箇所の共通契約
# --------------------------------------------------------------------------- #
def test_score_alert_is_noop_without_webhook_url(monkeypatch, fake_urlopen, capsys) -> None:
    monkeypatch.delenv("OPS_NOTIFY_WEBHOOK_URL", raising=False)
    sf._alert("degraded")
    assert fake_urlopen.reqs == []
    assert "[score][alert] (OPS_NOTIFY_WEBHOOK_URL unset) degraded" in capsys.readouterr().out


def test_weekly_notify_is_noop_without_webhook_url(monkeypatch, fake_urlopen, capsys) -> None:
    monkeypatch.delenv("OPS_NOTIFY_WEBHOOK_URL", raising=False)
    gwi._notify_ops("weekly failed")
    assert fake_urlopen.reqs == []
    assert "[weekly-insights][alert] (OPS_NOTIFY_WEBHOOK_URL unset) weekly failed" in capsys.readouterr().err


def test_score_alert_posts_json(monkeypatch, fake_urlopen, capsys) -> None:
    monkeypatch.setenv("OPS_NOTIFY_WEBHOOK_URL", "https://hooks.example/ops")
    monkeypatch.delenv("OPS_NOTIFY_WEBHOOK_TYPE", raising=False)
    sf._alert("degraded")
    assert len(fake_urlopen.reqs) == 1
    req = fake_urlopen.reqs[0]
    assert req.full_url == "https://hooks.example/ops"
    assert req.get_method() == "POST"
    assert req.headers.get("Content-type") == "application/json"
    assert fake_urlopen.payloads[0] == {"text": "degraded"}
    assert "[score][alert] sent: degraded" in capsys.readouterr().out


def test_weekly_notify_posts_json(monkeypatch, fake_urlopen, capsys) -> None:
    monkeypatch.setenv("OPS_NOTIFY_WEBHOOK_URL", "https://hooks.example/ops")
    monkeypatch.delenv("OPS_NOTIFY_WEBHOOK_TYPE", raising=False)
    gwi._notify_ops("weekly failed")
    assert len(fake_urlopen.reqs) == 1
    assert fake_urlopen.payloads[0] == {"text": "weekly failed"}
    assert "[weekly-insights][alert] sent: weekly failed" in capsys.readouterr().err


def test_send_failure_never_raises(monkeypatch, capsys) -> None:
    """送信失敗は呼び出し元の処理を止めない（ログだけ残す）。"""
    boom = _FakeUrlopen(fail=RuntimeError("boom"))
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    monkeypatch.setattr(gwi, "urlopen", boom)
    monkeypatch.setenv("OPS_NOTIFY_WEBHOOK_URL", "https://hooks.example/ops")
    sf._alert("degraded")
    gwi._notify_ops("weekly failed")
    captured = capsys.readouterr()
    assert "[score][alert] failed:" in captured.out
    assert "[weekly-insights][alert] failed to send:" in captured.err
