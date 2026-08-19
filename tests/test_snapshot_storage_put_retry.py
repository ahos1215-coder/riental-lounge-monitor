"""scripts/snapshot_forecasts.py の Storage 書き込み再試行の回帰テスト。

背景: _storage_put() には再試行が無く、Supabase Storage が 429/5xx を一度返した
だけでその夜の A スナップショットを丸ごと失っていた。翌朝の score_forecasts.py が
答え合わせできず、精度追跡に穴が空く（= 予測の劣化に気づけない）。

GET 側 (_get_json) と同じく指数バックオフで再試行する。ただし 401/403/404 の
ような恒久エラーは再試行せず即座に送出する（無駄な待ちを作らない）。

ネットワークは一切使わない（urlopen と sleep をモックする）。
"""

from __future__ import annotations

import urllib.error

import pytest

from scripts import snapshot_forecasts as snap


class _FakeUrlopen:
    """urlopen の代役。`outcomes` を先頭から順に消費する。

    outcome が Exception なら raise、そうでなければ成功扱い。
    """

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls: list[tuple[str, bytes]] = []

    def __call__(self, req, timeout=None):
        self.calls.append((req.full_url, req.data))
        outcome = self.outcomes.pop(0) if self.outcomes else None
        if isinstance(outcome, Exception):
            raise outcome
        return _FakeCtx()


class _FakeCtx:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return b""


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://x/y", code, "boom", {}, None)


@pytest.fixture
def no_sleep(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(snap.time, "sleep", lambda s: slept.append(s))
    return slept


def _put(monkeypatch, fake):
    monkeypatch.setattr(snap.urllib.request, "urlopen", fake)
    snap._storage_put(
        "ml-models",
        "accuracy/snapshots/20260819.json",
        b'{"a":1}',
        "https://example.supabase.co",
        "svc-key",
    )


def test_retries_after_transient_500_and_succeeds(monkeypatch, no_sleep):
    """1回目 500 → 2回目成功 で書き込みが成功すること。"""
    fake = _FakeUrlopen([_http_error(500), None])
    _put(monkeypatch, fake)
    assert len(fake.calls) == 2
    # 再送でも body が失われていない
    assert fake.calls[-1][1] == b'{"a":1}'
    assert no_sleep == [3]


def test_retries_after_rate_limit(monkeypatch, no_sleep):
    """429 も再試行対象。"""
    fake = _FakeUrlopen([_http_error(429), None])
    _put(monkeypatch, fake)
    assert len(fake.calls) == 2


def test_retries_after_network_error(monkeypatch, no_sleep):
    """URLError/timeout も再試行対象。"""
    fake = _FakeUrlopen([urllib.error.URLError("timed out"), None])
    _put(monkeypatch, fake)
    assert len(fake.calls) == 2


def test_gives_up_after_three_attempts(monkeypatch, no_sleep):
    """恒久的に 503 なら 3 回試して例外を送出する（黙って成功扱いにしない）。"""
    fake = _FakeUrlopen([_http_error(503), _http_error(503), _http_error(503)])
    monkeypatch.setattr(snap.urllib.request, "urlopen", fake)
    with pytest.raises(urllib.error.HTTPError):
        snap._storage_put(
            "ml-models", "p.json", b"{}", "https://example.supabase.co", "svc-key"
        )
    assert len(fake.calls) == 3


def test_does_not_retry_permanent_client_error(monkeypatch, no_sleep):
    """401 のような恒久エラーは 1 回で諦める（無駄な待ちを作らない）。"""
    fake = _FakeUrlopen([_http_error(401), None])
    monkeypatch.setattr(snap.urllib.request, "urlopen", fake)
    with pytest.raises(urllib.error.HTTPError):
        snap._storage_put(
            "ml-models", "p.json", b"{}", "https://example.supabase.co", "svc-key"
        )
    assert len(fake.calls) == 1
    assert no_sleep == []
