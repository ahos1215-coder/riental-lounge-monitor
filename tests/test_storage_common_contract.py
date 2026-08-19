"""Supabase Storage の GET/PUT 契約（scripts/_supabase_common.py）の番犬テスト。

B-01: `_storage_get` / `_storage_put` は score_forecasts.py / build_templates.py /
snapshot_forecasts.py / analytics_weekly_report.py の4本に手書きされ、
2026-08-18 の飽和事故対応の再試行がそのうち2本にしか入らなかった（乖離が拡大した）。

共通化にあたって「失敗時に何が起きるか」を4本まとめて固定する:

  GET: 404 -> None / 400+not_found -> None / 400+"object not found" -> None
       / 429・5xx -> 再試行して成功 / 401 -> 即 raise
  PUT: 429・5xx -> 再試行して成功 / 401・403・404 -> 即 raise

呼び出し元は `_storage_get` / `_storage_put` というモジュール変数名を維持しているので
（既存テストの monkeypatch.setattr(mod, "_storage_get", ...) がそのまま効く）、
ここでは各スクリプトのモジュール属性経由で契約を検証する。

ネットワークは一切使わない（urlopen / sleep をモックする）。
"""

from __future__ import annotations

import io
import urllib.error
import urllib.request

import pytest

from scripts import analytics_weekly_report as awr
from scripts import build_templates as bt
from scripts import score_forecasts as sf
from scripts import snapshot_forecasts as snap

# GET を持つスクリプト（共通化前は score / build の2本だけが再試行付きだった）
GET_MODULES = [
    pytest.param(sf, id="score_forecasts"),
    pytest.param(bt, id="build_templates"),
    pytest.param(snap, id="snapshot_forecasts"),
]

# PUT を持つスクリプト（共通化前は snapshot だけが再試行付きだった）
PUT_MODULES = [
    pytest.param(sf, id="score_forecasts"),
    pytest.param(bt, id="build_templates"),
    pytest.param(snap, id="snapshot_forecasts"),
    pytest.param(awr, id="analytics_weekly_report"),
]


class _FakeUrlopen:
    """urlopen の代役。`outcomes` を先頭から順に消費する（Exception なら raise）。"""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls: list[tuple[str, bytes | None]] = []

    def __call__(self, req, timeout=None):
        self.calls.append((req.full_url, req.data))
        outcome = self.outcomes.pop(0) if self.outcomes else _FakeCtx()
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _FakeCtx:
    def __init__(self, body: bytes = b"{}"):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body


def _http_error(code: int, body: bytes = b"") -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://x/y", code, "boom", {}, io.BytesIO(body))


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """time.sleep を潰す（time モジュールはプロセス共有なので全スクリプトに効く）。"""
    slept: list[float] = []
    import time as _time

    monkeypatch.setattr(_time, "sleep", lambda s: slept.append(s))
    return slept


def _patch_urlopen(monkeypatch: pytest.MonkeyPatch, fake: _FakeUrlopen) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", fake)


# --------------------------------------------------------------------------- #
# GET
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("mod", GET_MODULES)
def test_storage_get_returns_none_on_404(mod, monkeypatch, no_sleep) -> None:
    fake = _FakeUrlopen([_http_error(404)])
    _patch_urlopen(monkeypatch, fake)
    assert mod._storage_get("ml-models", "a/b.json", "https://x", "k") is None
    assert len(fake.calls) == 1


@pytest.mark.parametrize("mod", GET_MODULES)
@pytest.mark.parametrize("body", [b'{"error":"not_found"}', b'{"message":"Object not found"}'])
def test_storage_get_returns_none_on_400_not_found(mod, body, monkeypatch, no_sleep) -> None:
    """Storage は存在しないオブジェクトに 400 + not_found ボディを返すことがある。"""
    fake = _FakeUrlopen([_http_error(400, body)])
    _patch_urlopen(monkeypatch, fake)
    assert mod._storage_get("ml-models", "a/b.json", "https://x", "k") is None
    assert len(fake.calls) == 1


@pytest.mark.parametrize("mod", GET_MODULES)
def test_storage_get_returns_bytes_on_success(mod, monkeypatch, no_sleep) -> None:
    fake = _FakeUrlopen([_FakeCtx(b'{"ok":1}')])
    _patch_urlopen(monkeypatch, fake)
    assert mod._storage_get("ml-models", "a/b.json", "https://x", "k") == b'{"ok":1}'


@pytest.mark.parametrize("mod", GET_MODULES)
@pytest.mark.parametrize("code", [429, 500, 544, 503])
def test_storage_get_retries_transient_then_succeeds(mod, code, monkeypatch, no_sleep) -> None:
    """飽和系(429/5xx、544 DatabaseTimeout 含む)は再試行して成功させる。"""
    fake = _FakeUrlopen([_http_error(code), _FakeCtx(b'{"ok":1}')])
    _patch_urlopen(monkeypatch, fake)
    assert mod._storage_get("ml-models", "a/b.json", "https://x", "k") == b'{"ok":1}'
    assert len(fake.calls) == 2


@pytest.mark.parametrize("mod", GET_MODULES)
def test_storage_get_raises_immediately_on_permanent_4xx(mod, monkeypatch, no_sleep) -> None:
    """401 のような恒久エラーは再試行せず即座に送出する（無駄な待ちを作らない）。"""
    fake = _FakeUrlopen([_http_error(401), _FakeCtx()])
    _patch_urlopen(monkeypatch, fake)
    with pytest.raises(urllib.error.HTTPError):
        mod._storage_get("ml-models", "a/b.json", "https://x", "k")
    assert len(fake.calls) == 1
    assert no_sleep == []


# --------------------------------------------------------------------------- #
# PUT
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("mod", PUT_MODULES)
def test_storage_put_posts_upsert_json(mod, monkeypatch, no_sleep) -> None:
    """URL と body（x-upsert の POST）が従来どおりであること。"""
    fake = _FakeUrlopen([_FakeCtx()])
    _patch_urlopen(monkeypatch, fake)
    mod._storage_put("ml-models", "a/b.json", b'{"a":1}', "https://x", "k")
    assert fake.calls == [("https://x/storage/v1/object/ml-models/a/b.json", b'{"a":1}')]


@pytest.mark.parametrize("mod", PUT_MODULES)
@pytest.mark.parametrize("code", [429, 500, 503])
def test_storage_put_retries_transient_then_succeeds(mod, code, monkeypatch, no_sleep) -> None:
    fake = _FakeUrlopen([_http_error(code), _FakeCtx()])
    _patch_urlopen(monkeypatch, fake)
    mod._storage_put("ml-models", "a/b.json", b'{"a":1}', "https://x", "k")
    assert len(fake.calls) == 2
    # 再送でも body が失われていない
    assert fake.calls[-1][1] == b'{"a":1}'


@pytest.mark.parametrize("mod", PUT_MODULES)
@pytest.mark.parametrize("code", [401, 403, 404])
def test_storage_put_raises_immediately_on_permanent_4xx(mod, code, monkeypatch, no_sleep) -> None:
    fake = _FakeUrlopen([_http_error(code), _FakeCtx()])
    _patch_urlopen(monkeypatch, fake)
    with pytest.raises(urllib.error.HTTPError):
        mod._storage_put("ml-models", "a/b.json", b"{}", "https://x", "k")
    assert len(fake.calls) == 1
    assert no_sleep == []
