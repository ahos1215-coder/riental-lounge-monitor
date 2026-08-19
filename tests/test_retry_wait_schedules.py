"""各バッチスクリプトの「再試行の待ち秒の列」をフィクスチャとして固定する番犬。

B-08 の共通化（scripts/_retry_common.py）を進めるとき、いちばん怖いのは
「式を共通化したつもりで待ち秒が変わり、混雑中の Supabase を以前より速く叩いて
事故を悪化させる」こと。ここでは各スクリプトの再試行ループを実際に回して
（ネットワークは使わず urlopen / requests.Session をモックする）、
`time.sleep` に渡された秒数の列そのものを固定する。

指数（`backoff_delay`）と線形（`3*attempt` / `2*attempt`）が混在しているのは意図的で、
それぞれの理由は呼び出し元のコメントに書いてある。ここはその**現状**を写し取るだけ。
"""

from __future__ import annotations

import io
import urllib.error
import urllib.request

import pytest

from scripts import backup_logs as bl
from scripts import build_templates as bt
from scripts import score_forecasts as sf
from scripts import snapshot_forecasts as snap
from scripts import _supabase_common as sc


def _http_error(code: int, body: bytes = b"") -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://x/y", code, "boom", {}, io.BytesIO(body))


class _AlwaysFails:
    """urlopen の代役。毎回同じ例外を投げ、呼ばれた回数を数える。"""

    def __init__(self, exc_factory):
        self._exc_factory = exc_factory
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        raise self._exc_factory()


@pytest.fixture
def slept(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """time.sleep に渡された秒数を記録する（time モジュールはプロセス共有）。"""
    out: list[float] = []
    import time as _time

    monkeypatch.setattr(_time, "sleep", lambda s: out.append(float(s)))
    return out


def _patch_urlopen(monkeypatch: pytest.MonkeyPatch, fake) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", fake)


# --------------------------------------------------------------------------- #
# 共通 Storage ヘルパー（_supabase_common）
# --------------------------------------------------------------------------- #
def test_storage_getの待ち秒列(monkeypatch, slept) -> None:
    """指数 min(2**attempt, 30)、6 試行 = 5 回の待ち。"""
    fake = _AlwaysFails(lambda: _http_error(500))
    _patch_urlopen(monkeypatch, fake)
    with pytest.raises(urllib.error.HTTPError):
        sc.storage_get("ml-models", "a/b.json", "https://x", "k")
    assert fake.calls == 6
    assert slept == [2, 4, 8, 16, 30]


def test_storage_putの待ち秒列(monkeypatch, slept) -> None:
    """意図的に線形 3*attempt、3 試行 = 2 回の待ち。"""
    fake = _AlwaysFails(lambda: _http_error(500))
    _patch_urlopen(monkeypatch, fake)
    with pytest.raises(urllib.error.HTTPError):
        sc.storage_put("ml-models", "a/b.json", b"{}", "https://x", "k")
    assert fake.calls == 3
    assert slept == [3, 6]


# --------------------------------------------------------------------------- #
# backup_logs（logs 全件ダンプ。~1,300 リクエストを直列に投げるため試行数が多い）
# --------------------------------------------------------------------------- #
def test_backup_logsのfetch待ち秒列(monkeypatch, slept) -> None:
    fake = _AlwaysFails(lambda: _http_error(500))
    _patch_urlopen(monkeypatch, fake)
    with pytest.raises(SystemExit):
        bl._get("https://x/rest/v1/logs", "k", [("select", "id")])
    assert fake.calls == bl.FETCH_RETRIES == 10
    assert slept == [2, 4, 8, 16, 32, 45, 45, 45, 45]


# --------------------------------------------------------------------------- #
# build_templates（1 店ぶんの実測ページング）
# --------------------------------------------------------------------------- #
def test_build_templatesのfetch待ち秒列(monkeypatch, slept) -> None:
    """指数 min(2**attempt, 10)、4 試行 = 3 回の待ち。"""
    fake = _AlwaysFails(lambda: _http_error(500))
    _patch_urlopen(monkeypatch, fake)
    rows = bt._fetch_store_rows("https://x", "k", "ol_shibuya", "2026-01-01T00:00:00+00:00")
    assert rows == []
    assert fake.calls == 4
    assert slept == [2, 4, 8]


def test_build_templatesは恒久4xxで即あきらめる(monkeypatch, slept) -> None:
    fake = _AlwaysFails(lambda: _http_error(401))
    _patch_urlopen(monkeypatch, fake)
    assert bt._fetch_store_rows("https://x", "k", "ol_shibuya", "2026-01-01T00:00:00+00:00") == []
    assert fake.calls == 1
    assert slept == []


# --------------------------------------------------------------------------- #
# score_forecasts / snapshot_forecasts（意図的に線形のまま）
# --------------------------------------------------------------------------- #
def test_score_forecastsのfetch待ち秒列(monkeypatch, slept) -> None:
    """意図的に線形 2*attempt、3 試行 = 2 回の待ち。"""
    fake = _AlwaysFails(lambda: _http_error(500))
    _patch_urlopen(monkeypatch, fake)
    rows = sf._fetch_actuals(
        "https://x", "k", "ol_shibuya", "2026-01-01T10:00:00+00:00", "2026-01-01T20:00:00+00:00"
    )
    assert rows == []
    assert fake.calls == 3
    assert slept == [2, 4]


def test_snapshot_forecastsのget_json待ち秒列(monkeypatch, slept) -> None:
    """意図的に線形 3*attempt、3 試行 = 2 回の待ち。"""
    fake = _AlwaysFails(lambda: _http_error(500))
    _patch_urlopen(monkeypatch, fake)
    assert snap._get_json("https://x/api/forecast_today?store=shibuya") is None
    assert fake.calls == 3
    assert slept == [3, 6]


# --------------------------------------------------------------------------- #
# train_ml_model（Storage アップロード。指数だが係数 2.5 = 旧 5*2**(attempt-1)）
# --------------------------------------------------------------------------- #
class _FailingSession:
    def __init__(self, status_code: int) -> None:
        self._status = status_code
        self.calls = 0

    def post(self, *args, **kwargs):
        self.calls += 1
        return _FakeResponse(self._status)


class _FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self.text = "boom"


def test_train_ml_modelのアップロード待ち秒列(monkeypatch, slept, tmp_path) -> None:
    """min(5 * 2**(attempt-1), 60) = backoff_delay(attempt, cap=60, factor=2.5)。"""
    import types

    tml = pytest.importorskip("scripts.train_ml_model")
    payload = tmp_path / "model.bin"
    payload.write_bytes(b"x")
    # _upload_file が cfg から読むのは URL/キー/バケット/プレフィックスの4つだけ。
    cfg = types.SimpleNamespace(
        supabase_url="https://x",
        supabase_service_key="k",
        bucket="ml-models",
        prefix="forecast/latest",
    )
    session = _FailingSession(500)
    with pytest.raises(SystemExit):
        tml._upload_file(
            cfg=cfg,
            session=session,
            local_path=payload,
            remote_name="model.bin",
            content_type="application/octet-stream",
        )
    assert session.calls == 6
    assert slept == [5, 10, 20, 40, 60]
