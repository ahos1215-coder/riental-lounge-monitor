"""/api/range, /api/range_multi の in-process TTL キャッシュ + single-flight
合流のテスト（oriental/routes/data.py, perf: backend cache/coalesce タスク）。

背景: 実測で /api/range, /api/range_multi にはキャッシュが一切無く、CDN
キャッシュが外れるたびに Supabase への live クエリが発生していた
（range_multi 12店舗 cold で ~5.9s）。本テストは、

  1. 同一キーへの繰り返しリクエストが Supabase への再問い合わせを起こさない
     こと（TTL キャッシュのヒット）。
  2. /api/range（単体）と /api/range_multi（内部の店舗別 fetch）が同じ
     store_id/期間/limit のキャッシュキーを共有すること（サーバー側/クライア
     ント側から同時に来ても Supabase 問い合わせが1回で済む）。
  3. TTL が切れたら再計算されること。
  4. 上流エラーはキャッシュされず、次のリクエストで再試行されること。
  5. 同時アクセスが cold なとき、single-flight で計算が1回に合流すること。

を回帰確認する。Supabase 自体はフェイクプロバイダで完全に差し替え、実ネット
ワークには一切依存しない。
"""

from __future__ import annotations

import datetime as dt
import threading
import time as time_module

import pytest

from oriental import create_app
from oriental.data.provider import SupabaseError
from oriental.routes._cache import SingleFlightTTLCache


class _FakeProvider:
    """SupabaseLogsProvider の代わりに使うフェイク。

    - `calls` に呼ばれた store_id を記録する（何回 Supabase 相当に問い合わせが
      行ったかを検証するため）。
    - `block_until_released()` を呼んでおくと、`fetch_range()` は
      `release()` が呼ばれるまでブロックする（single-flight の合流テスト用）。
    - `error_stores` に入れた store_id は SupabaseError を送出する。
    """

    def __init__(self, rows_by_store: dict | None = None):
        self.rows_by_store = rows_by_store or {}
        self.error_stores: set[str] = set()
        self.calls: list[str] = []
        self._lock = threading.Lock()
        self._release = threading.Event()
        self._release.set()

    def block_until_released(self) -> None:
        self._release.clear()

    def release(self) -> None:
        self._release.set()

    def fetch_range(self, *, store_id, limit, start_ts=None, end_ts=None):
        with self._lock:
            self.calls.append(store_id)
        self._release.wait(timeout=5)
        if store_id in self.error_stores:
            raise SupabaseError("boom")
        return list(self.rows_by_store.get(store_id, []))


@pytest.fixture
def app_and_provider(monkeypatch):
    monkeypatch.setenv("DATA_BACKEND", "supabase")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-key")
    monkeypatch.setenv("DISABLE_MODEL_PRELOAD", "1")

    from oriental.routes import data as data_module

    provider = _FakeProvider(rows_by_store={
        "ol_gangnam": [
            {"ts": "2026-07-09T23:00:00+09:00", "men": 3, "women": 4, "total": 7},
        ],
    })
    # get_supabase_provider() 経由の実体生成/キャッシュを完全にバイパスし、
    # 常にこのフェイクを返すようにする（second_venues のテストと同じ手法）。
    monkeypatch.setattr(data_module, "_supabase_provider", lambda cfg: provider)

    app = create_app()
    return app, provider


RANGE_URL = "/api/range?store=gangnam&from=2026-07-01&to=2026-07-02"
RANGE_MULTI_URL = "/api/range_multi?stores=gangnam&from=2026-07-01&to=2026-07-02"


def test_range_cache_key_normalization():
    from oriental.routes.data import _range_cache_key

    k1 = _range_cache_key("ol_gangnam", dt.date(2026, 7, 1), dt.date(2026, 7, 2), 500)
    k1_again = _range_cache_key("ol_gangnam", dt.date(2026, 7, 1), dt.date(2026, 7, 2), 500)
    k_diff_store = _range_cache_key("ol_shibuya", dt.date(2026, 7, 1), dt.date(2026, 7, 2), 500)
    k_diff_window = _range_cache_key("ol_gangnam", dt.date(2026, 7, 1), dt.date(2026, 7, 3), 500)
    k_diff_limit = _range_cache_key("ol_gangnam", dt.date(2026, 7, 1), dt.date(2026, 7, 2), 100)
    k_no_window = _range_cache_key("ol_gangnam", None, None, 500)

    assert k1 == k1_again
    assert len({k1, k_diff_store, k_diff_window, k_diff_limit, k_no_window}) == 5


def test_range_endpoint_hits_cache_on_repeat_request(app_and_provider):
    app, provider = app_and_provider
    client = app.test_client()

    resp1 = client.get(RANGE_URL)
    resp2 = client.get(RANGE_URL)

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp1.get_json() == resp2.get_json()
    assert provider.calls == ["ol_gangnam"]  # 2回目はキャッシュヒットで再問い合わせなし


def test_range_and_range_multi_share_cache(app_and_provider):
    """店舗ページのサーバー側 /api/range とクライアント側 /api/range_multi が
    ほぼ同時に来ても、同じ店舗+期間+limit なら Supabase 問い合わせは1回で済む。"""
    app, provider = app_and_provider
    client = app.test_client()

    resp1 = client.get(RANGE_URL)
    assert resp1.status_code == 200

    resp2 = client.get(RANGE_MULTI_URL)
    assert resp2.status_code == 200
    by_slug = resp2.get_json()["by_slug"]
    assert by_slug["gangnam"]["rows"] == resp1.get_json()["rows"]

    assert provider.calls == ["ol_gangnam"]


def test_range_cache_ttl_expiry(app_and_provider):
    app, provider = app_and_provider
    client = app.test_client()

    # TTL を短くした専用キャッシュに差し替える（env の RANGE_CACHE_TTL はモジュール
    # import 時に評価済みのため、テストからは app.config 経由で直接差し替える）。
    app.config["RANGE_RESULT_CACHE"] = SingleFlightTTLCache(ttl=0.05, wait_timeout=5)

    client.get(RANGE_URL)
    assert provider.calls == ["ol_gangnam"]

    time_module.sleep(0.15)
    client.get(RANGE_URL)
    assert provider.calls == ["ol_gangnam", "ol_gangnam"]  # TTL 切れ -> 再計算


def test_range_upstream_error_is_not_cached(app_and_provider):
    app, provider = app_and_provider
    provider.error_stores.add("ol_gangnam")
    client = app.test_client()

    resp1 = client.get(RANGE_URL)
    resp2 = client.get(RANGE_URL)

    assert resp1.status_code == 502
    assert resp2.status_code == 502
    # cacheable=False なので毎回 Supabase に再試行する（エラーを 120 秒引きずらない）
    assert provider.calls == ["ol_gangnam", "ol_gangnam"]


def test_range_multi_error_is_not_cached(app_and_provider):
    app, provider = app_and_provider
    provider.error_stores.add("ol_gangnam")
    client = app.test_client()

    resp1 = client.get(RANGE_MULTI_URL)
    resp2 = client.get(RANGE_MULTI_URL)

    assert resp1.status_code == 200  # multi は店舗別エラーを埋め込みつつ全体は 200
    assert resp2.status_code == 200
    assert resp1.get_json()["by_slug"]["gangnam"]["ok"] is False
    assert resp2.get_json()["by_slug"]["gangnam"]["ok"] is False
    assert provider.calls == ["ol_gangnam", "ol_gangnam"]


def test_range_single_flight_coalesces_concurrent_requests(app_and_provider):
    app, provider = app_and_provider
    provider.block_until_released()

    results: list[int] = []
    results_lock = threading.Lock()

    def worker():
        local_client = app.test_client()
        resp = local_client.get(RANGE_URL)
        with results_lock:
            results.append(resp.status_code)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()

    # leader が provider.fetch_range() に入り、ブロックし始めるのを待つ
    deadline = time_module.time() + 5
    while len(provider.calls) < 1 and time_module.time() < deadline:
        time_module.sleep(0.01)
    time_module.sleep(0.2)  # 残りのフォロワーが合流待ちに入る猶予
    provider.release()

    for t in threads:
        t.join(timeout=5)

    assert results == [200] * 6
    assert provider.calls == ["ol_gangnam"]  # 6並列でも Supabase 問い合わせは1回だけ
