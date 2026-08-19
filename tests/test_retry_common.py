"""バックオフ／再試行判定（scripts/_retry_common.py）の番犬テスト。

B-08: `backoff_delay` / `is_retryable_status` は backup_logs.py / cleanup_old_logs.py /
cleanup_old_models.py に3本コピーされていた。共通化するにあたって重要なのは
「待ち秒数が1秒たりとも変わらないこと」なので、

  (1) 各スクリプトの (cap, attempts) の表
  (2) 実際の再試行コードパス（urlopen をモックして 429/5xx を返す）で
      time.sleep に渡された実測秒数

の両方を固定する。特に (2) は、統一シグネチャ `backoff_delay(attempt, cap, retry_after)`
へ寄せた際に backup_logs.py の旧シグネチャ（第2位置引数が retry_after）の呼び出しを
書き換え忘れて「Retry-After が cap として解釈される」退行を直接検出するためのもの。
既存 tests/test_ops_safety.py は全てキーワード引数で呼んでいるためこのバグを検出できない。

ネットワークは一切使わない（urlopen / sleep をモックする）。
"""

from __future__ import annotations

import urllib.error

import pytest

from scripts import backup_logs as bl
from scripts import cleanup_old_logs as col
from scripts import cleanup_old_models as com


# --------------------------------------------------------------------------- #
# (1) 各スクリプトの再試行バジェット表（cap 秒 / 最大試行回数）
# --------------------------------------------------------------------------- #
def test_retry_budget_table_is_unchanged() -> None:
    """「どのジョブが何秒まで粘るか」の一覧。既定値を変えたらここが落ちる。"""
    assert (bl.BACKOFF_MAX_SEC, bl.FETCH_RETRIES) == (45.0, 10)
    assert (col.CLEANUP_BACKOFF_MAX_SEC, col.CLEANUP_RETRIES) == (45.0, 8)
    assert com.CleanupConfig.__dataclass_fields__["backoff_max_sec"].default == 45.0
    assert com.CleanupConfig.__dataclass_fields__["retries"].default == 8


def test_is_retryable_status_agrees_across_scripts() -> None:
    """cleanup_old_logs と cleanup_old_models の判定は同一でなければならない。"""
    for code in (429, 500, 502, 503, 504, 544):
        assert col.is_retryable_status(code) is True, code
        assert com.is_retryable_status(code) is True, code
    for code in (200, 400, 401, 403, 404, 409, 422):
        assert col.is_retryable_status(code) is False, code
        assert com.is_retryable_status(code) is False, code


# --------------------------------------------------------------------------- #
# (2) 実呼び出しパスで time.sleep に渡る秒数（引数順の取り違えを直接検出する）
# --------------------------------------------------------------------------- #
class _FakeUrlopen:
    """urlopen の代役。`outcomes` を先頭から順に消費する（Exception なら raise）。"""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def __call__(self, req, timeout=None):
        self.calls += 1
        outcome = self.outcomes.pop(0) if self.outcomes else _FakeResp()
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _FakeResp:
    def __init__(self, body: bytes = b"[]", headers: dict | None = None):
        self._body = body
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body


def _http_error(code: int, headers: dict | None = None) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://x/y", code, "boom", headers or {}, None)


def test_backup_logs_get_sleeps_exponentially(monkeypatch: pytest.MonkeyPatch) -> None:
    """backup_logs._get: 500 が3回続いたら 2s, 4s, 8s と待つ（cap 45s）。"""
    slept: list[float] = []
    monkeypatch.setattr(bl.time, "sleep", lambda s: slept.append(s))
    fake = _FakeUrlopen([_http_error(500), _http_error(500), _http_error(500), _FakeResp(b"[]")])
    monkeypatch.setattr(bl.urllib.request, "urlopen", fake)

    assert bl._get("https://x/rest/v1/logs", "k", [("select", "id")]) == []
    assert slept == [2, 4, 8]


def test_backup_logs_get_honours_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    """429 + Retry-After: 30 なら、計算値(2s)ではなく 30s 待つ。

    共通化で `backoff_delay(attempt, cap, retry_after)` へ寄せる際、backup_logs 側の
    位置引数呼び出し（旧: 第2引数=retry_after）を書き換え忘れると、ここが 30 ではなく
    2（retry_after が cap として解釈される）になって落ちる。
    """
    slept: list[float] = []
    monkeypatch.setattr(bl.time, "sleep", lambda s: slept.append(s))
    fake = _FakeUrlopen([_http_error(429, {"Retry-After": "30"}), _FakeResp(b"[]")])
    monkeypatch.setattr(bl.urllib.request, "urlopen", fake)

    assert bl._get("https://x/rest/v1/logs", "k", [("select", "id")]) == []
    assert slept == [30]


def test_backup_logs_get_caps_absurd_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    """Retry-After が巨大でも cap(45s)で頭打ちにする。"""
    slept: list[float] = []
    monkeypatch.setattr(bl.time, "sleep", lambda s: slept.append(s))
    fake = _FakeUrlopen([_http_error(429, {"Retry-After": "9999"}), _FakeResp(b"[]")])
    monkeypatch.setattr(bl.urllib.request, "urlopen", fake)

    bl._get("https://x/rest/v1/logs", "k", [("select", "id")])
    assert slept == [45]


def test_cleanup_old_logs_rest_request_sleeps_exponentially(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """cleanup_old_logs._rest_request: 500 が2回で 2s, 4s（cap 45s）。"""
    slept: list[float] = []
    monkeypatch.setattr(col.time, "sleep", lambda s: slept.append(s))
    fake = _FakeUrlopen([_http_error(500), _http_error(500), _FakeResp(b"[]")])
    monkeypatch.setattr(col, "urlopen", fake)

    body, _headers = col._rest_request(object(), what="test")
    assert body == b"[]"
    assert slept == [2, 4]


def test_cleanup_old_models_storage_request_sleeps_exponentially(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """cleanup_old_models._storage_request: cfg.backoff_max_sec が cap として効く。"""
    slept: list[float] = []
    monkeypatch.setattr(com.time, "sleep", lambda s: slept.append(s))
    fake = _FakeUrlopen([_http_error(503), _http_error(503), _FakeResp(b"[]")])
    monkeypatch.setattr(com, "urlopen", fake)

    cfg = com.CleanupConfig(
        supabase_url="https://x",
        supabase_key="k",
        bucket="ml-models",
        prefix="forecast/latest",
        backoff_max_sec=3.0,
    )
    assert com._storage_request(object(), cfg=cfg, what="test") == b"[]"
    # cap=3 なので 2s のあと 4s ではなく 3s で頭打ち。
    assert slept == [2, 3]
