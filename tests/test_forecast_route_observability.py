"""/api/forecast_today (+ next_hour / today_multi) が後処理の観測フィールド
(blend_w_ml, blended_slots, clamped_slots) を透過することのテスト。

背景: oriental/ml/forecast_service.py の _forecast_generic はブレンド/クランプが
実際に効いたかどうかを raw 結果に含めて返す（forecast_service.py 参照）。しかし
ルート側は独自の result dict を組み立てており、この3フィールドを素通りさせて
いなかったため、後処理が本番で本当に効いているか API 経由では一切観測できな
かった（生成された response には blend_w_ml/blended_slots/clamped_slots が
含まれない）。本テストはこの回帰を防ぐ。

Service は完全にモックし、DB/モデルには一切依存しない。
"""

from __future__ import annotations

import pytest

from oriental import create_app


class _FakeService:
    """ForecastService の代わりに固定の raw 結果を返すフェイク。"""

    def __init__(self, raw: dict):
        self._raw = raw

    def forecast_today(self, *, store_id, freq_min, start_h, end_h):
        return dict(self._raw)

    def forecast_next_hour(self, *, store_id, freq_min):
        return dict(self._raw)


RAW_WITH_POSTPROCESS = {
    "ok": True,
    "store": "ol_gangnam",
    "freq_min": 15,
    "data": [
        {"ts": "2026-07-09T23:00:00+09:00", "men_pred": 5.0, "women_pred": 5.0, "total_pred": 10.0},
        {"ts": "2026-07-09T23:15:00+09:00", "men_pred": 4.0, "women_pred": 4.0, "total_pred": 8.0},
    ],
    "reasoning": {"signals": {}, "notes": ["通常条件で推論"]},
    "insufficient_history": False,
    "blend_w_ml": 0.197,
    "blended_slots": 2,
    "clamped_slots": 1,
}


@pytest.fixture
def fake_service(monkeypatch):
    """oriental.routes.forecast._service() を差し替える。

    create_app() はバックグラウンドスレッドで本物の ForecastService を生成し
    app.config["FORECAST_SERVICE"] へ書き込む（oriental/__init__.py の
    model_preload）。テスト側でその後 app.config を上書きしても、スレッドの
    完了タイミング次第でレースし本物に戻ってしまうことがあるため、
    app.config を触るのではなく _service() 自体を差し替えて確実にモックへ
    固定する。
    """
    service = _FakeService(RAW_WITH_POSTPROCESS)
    monkeypatch.setattr("oriental.routes.forecast._service", lambda: service)
    return service


@pytest.fixture
def app_client(monkeypatch, fake_service):
    monkeypatch.setenv("ENABLE_FORECAST", "1")
    app = create_app()
    return app.test_client()


def test_forecast_today_passes_through_postprocess_fields(app_client):
    resp = app_client.get("/api/forecast_today?store=gangnam")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["blend_w_ml"] == 0.197
    assert body["blended_slots"] == 2
    assert body["clamped_slots"] == 1
    # 既存フィールドが壊れていないことも確認（後方互換の追加であること）
    assert body["insufficient_history"] is False
    assert len(body["data"]) == 2


def test_forecast_next_hour_passes_through_postprocess_fields(app_client):
    resp = app_client.get("/api/forecast_next_hour?store=gangnam")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["blend_w_ml"] == 0.197
    assert body["blended_slots"] == 2
    assert body["clamped_slots"] == 1


def test_forecast_today_missing_postprocess_fields_default_to_none(app_client, fake_service):
    """後処理フィールドが raw に無い（旧サービス実装/例外経路）場合でも
    ルートは落ちず、新フィールドは None になる（後方互換）。"""
    raw_without = {
        "ok": True,
        "data": [{"ts": "2026-07-09T23:00:00+09:00", "total_pred": 10.0}],
        "reasoning": {},
        "insufficient_history": False,
    }
    fake_service._raw = raw_without
    resp = app_client.get("/api/forecast_today?store=gangnam")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["blend_w_ml"] is None
    assert body["blended_slots"] is None
    assert body["clamped_slots"] is None


def test_forecast_today_multi_passes_through_postprocess_fields_per_store(app_client):
    resp = app_client.get("/api/forecast_today_multi?stores=gangnam")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    entry = body["by_slug"]["gangnam"]
    assert entry["ok"] is True
    assert entry["blend_w_ml"] == 0.197
    assert entry["blended_slots"] == 2
    assert entry["clamped_slots"] == 1
