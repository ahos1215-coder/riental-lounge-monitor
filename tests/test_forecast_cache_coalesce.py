"""/api/forecast_today 系の TTL キャッシュ + single-flight 合流のテスト
（oriental/routes/forecast.py, perf: backend cache/coalesce タスク）。

背景: forecast_today には 180秒 TTL の in-process キャッシュがあったが
single-flight 合流が無く、店舗ページ1回の表示でサーバー側レンダリングと
クライアント側 fetch がほぼ同時に forecast_today を叩くと、両方 cold な
タイミングで2回とも ML 推論が走っていた（1 page view = 2x compute）。

本テストは以下を回帰確認する:
  1. 同一店舗への繰り返しリクエストが ML 再計算を起こさない（TTL キャッシュ）。
  2. /api/forecast_today（単体）と /api/forecast_today_multi（内部の店舗別
     fetch）が同じ店舗のキャッシュキーを共有すること（== 1 page view = 1x
     compute の直接的な検証）。
  3. 上流エラーはキャッシュされないこと。
  4. 同時アクセスが cold なとき、single-flight で ML 計算が1回に合流すること
     （forecast_next_hour にも同じ仕組みが使われていることも合わせて確認）。

ForecastService は完全にフェイクへ差し替え、実モデル/Supabase には一切
依存しない（test_forecast_route_observability.py と同じ手法）。
"""

from __future__ import annotations

import threading
import time as time_module

import pytest

from oriental import create_app


class _FakeForecastService:
    """ForecastService の代わりに使うフェイク。

    - `calls` に呼ばれた store_id を記録する（ML 推論が何回走ったかの検証用）。
    - `block_until_released()` を呼んでおくと `forecast_today`/
      `forecast_next_hour` は `release()` まで実際にブロックする
      （single-flight の合流テスト用 — 本物の ML 推論が重い処理であることを
      模している）。
    - `error_stores` に入れた store_id は forecast_internal_error を返す。
    """

    def __init__(self):
        self.calls: list[str] = []
        self.error_stores: set[str] = set()
        self._lock = threading.Lock()
        self._release = threading.Event()
        self._release.set()

    def block_until_released(self) -> None:
        self._release.clear()

    def release(self) -> None:
        self._release.set()

    def _raw_for(self, store_id: str) -> dict:
        with self._lock:
            self.calls.append(store_id)
        self._release.wait(timeout=5)
        if store_id in self.error_stores:
            return {"ok": False, "error": "forecast_internal_error", "detail": "boom"}
        return {
            "ok": True,
            "data": [
                {"ts": "2026-07-09T23:00:00+09:00", "men_pred": 3.0, "women_pred": 4.0, "total_pred": 7.0},
            ],
            "reasoning": {"signals": {}, "notes": []},
            "insufficient_history": False,
            "blend_w_ml": 0.2,
            "blended_slots": 1,
            "clamped_slots": 0,
        }

    def forecast_today(self, *, store_id, freq_min, start_h, end_h):
        return self._raw_for(store_id)

    def forecast_next_hour(self, *, store_id, freq_min):
        return self._raw_for(store_id)


@pytest.fixture
def app_and_service(monkeypatch):
    monkeypatch.setenv("ENABLE_FORECAST", "1")
    monkeypatch.setenv("DISABLE_MODEL_PRELOAD", "1")

    service = _FakeForecastService()
    # model_preload のバックグラウンドスレッドとのレースを避けるため、
    # app.config を触るのではなく _service() 自体を固定する
    # （test_forecast_route_observability.py と同じ理由）。
    monkeypatch.setattr("oriental.routes.forecast._service", lambda: service)

    app = create_app()
    return app, service


def test_forecast_today_cache_hit_avoids_recompute(app_and_service):
    app, service = app_and_service
    client = app.test_client()

    resp1 = client.get("/api/forecast_today?store=gangnam")
    resp2 = client.get("/api/forecast_today?store=gangnam")

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp1.get_json() == resp2.get_json()
    assert service.calls == ["ol_gangnam"]


def test_forecast_next_hour_cache_hit_avoids_recompute(app_and_service):
    app, service = app_and_service
    client = app.test_client()

    resp1 = client.get("/api/forecast_next_hour?store=gangnam")
    resp2 = client.get("/api/forecast_next_hour?store=gangnam")

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert service.calls == ["ol_gangnam"]


def test_forecast_today_and_today_multi_share_cache(app_and_service):
    """本タスクの前提そのもの: サーバー側 forecast_today とクライアント側
    forecast_today_multi がほぼ同時に来ても ML 計算は1回で済むこと。"""
    app, service = app_and_service
    client = app.test_client()

    resp1 = client.get("/api/forecast_today?store=gangnam")
    assert resp1.status_code == 200

    resp2 = client.get("/api/forecast_today_multi?stores=gangnam")
    assert resp2.status_code == 200
    entry = resp2.get_json()["by_slug"]["gangnam"]
    assert entry["ok"] is True
    assert entry["data"] == resp1.get_json()["data"]
    assert entry["blend_w_ml"] == resp1.get_json()["blend_w_ml"]

    assert service.calls == ["ol_gangnam"]  # 2エンドポイント合わせて ML 計算は1回のみ


def test_forecast_today_multi_then_single_also_shares_cache(app_and_service):
    """逆順（multi が先）でも合流すること。"""
    app, service = app_and_service
    client = app.test_client()

    resp1 = client.get("/api/forecast_today_multi?stores=gangnam")
    assert resp1.status_code == 200

    resp2 = client.get("/api/forecast_today?store=gangnam")
    assert resp2.status_code == 200

    assert service.calls == ["ol_gangnam"]


def test_forecast_error_response_is_not_cached(app_and_service):
    app, service = app_and_service
    service.error_stores.add("ol_gangnam")
    client = app.test_client()

    resp1 = client.get("/api/forecast_today?store=gangnam")
    resp2 = client.get("/api/forecast_today?store=gangnam")

    assert resp1.status_code == 500
    assert resp2.status_code == 500
    assert service.calls == ["ol_gangnam", "ol_gangnam"]


def test_forecast_today_multi_error_is_not_cached(app_and_service):
    app, service = app_and_service
    service.error_stores.add("ol_gangnam")
    client = app.test_client()

    resp1 = client.get("/api/forecast_today_multi?stores=gangnam")
    resp2 = client.get("/api/forecast_today_multi?stores=gangnam")

    assert resp1.status_code == 200  # multi は店舗別エラーを埋め込みつつ全体は 200
    assert resp2.status_code == 200
    assert resp1.get_json()["by_slug"]["gangnam"]["ok"] is False
    assert resp2.get_json()["by_slug"]["gangnam"]["ok"] is False
    assert service.calls == ["ol_gangnam", "ol_gangnam"]


def test_forecast_today_single_flight_coalesces_concurrent_requests(app_and_service):
    app, service = app_and_service
    service.block_until_released()

    results: list[int] = []
    results_lock = threading.Lock()

    def worker():
        local_client = app.test_client()
        resp = local_client.get("/api/forecast_today?store=gangnam")
        with results_lock:
            results.append(resp.status_code)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()

    deadline = time_module.time() + 5
    while len(service.calls) < 1 and time_module.time() < deadline:
        time_module.sleep(0.01)
    time_module.sleep(0.2)
    service.release()

    for t in threads:
        t.join(timeout=5)

    assert results == [200] * 6
    assert service.calls == ["ol_gangnam"]  # 6並列でも ML 計算は1回だけ


def test_forecast_today_multi_single_flight_coalesces_with_single_endpoint(app_and_service):
    """店舗ページのサーバー側 forecast_today とクライアント側
    forecast_today_multi がほぼ同時（cold な状態で並行）に来ても、片方だけが
    ML を計算し、もう片方は合流すること。"""
    app, service = app_and_service
    service.block_until_released()

    results: dict[str, int] = {}
    results_lock = threading.Lock()

    def call_single():
        local_client = app.test_client()
        resp = local_client.get("/api/forecast_today?store=gangnam")
        with results_lock:
            results["single"] = resp.status_code

    def call_multi():
        local_client = app.test_client()
        resp = local_client.get("/api/forecast_today_multi?stores=gangnam")
        with results_lock:
            results["multi"] = resp.status_code

    t1 = threading.Thread(target=call_single)
    t2 = threading.Thread(target=call_multi)
    t1.start()
    t2.start()

    deadline = time_module.time() + 5
    while len(service.calls) < 1 and time_module.time() < deadline:
        time_module.sleep(0.01)
    time_module.sleep(0.2)
    service.release()

    t1.join(timeout=5)
    t2.join(timeout=5)

    assert results == {"single": 200, "multi": 200}
    assert service.calls == ["ol_gangnam"]
