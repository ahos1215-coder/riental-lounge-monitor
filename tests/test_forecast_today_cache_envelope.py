"""/api/forecast_today と /api/forecast_today_multi のキャッシュ共有に関する回帰テスト。

背景:
両エンドポイントは同じキャッシュキー "today:<store_id>" を共有する（ML 推論を
1回にまとめるための single-flight 合流）。ところが multi 側の _compute は
{ok,data,blend_w_ml,blended_slots,clamped_slots} しかキャッシュに入れていなかった
ため、multi が先に温めた 180 秒の間、単体 /api/forecast_today のレスポンスから
insufficient_history / reasoning が丸ごと欠落していた。

フロント (useStorePreviewData.ts) は insufficient_history を見て
「データ準備中」表示に落とすので、欠落すると「再試行 → unavailable」という
誤った表示になる（履歴が無いだけの新店で発生）。

修正後は multi も単体と同じ完全エンベロープをキャッシュし、multi のレスポンス側
だけを _multi_entry() で従来の形に絞る。
"""

from __future__ import annotations

import pytest

from oriental import create_app


class _FakeService:
    def __init__(self, raw: dict):
        self._raw = raw
        self.calls = 0

    def forecast_today(self, *, store_id, freq_min, start_h, end_h):
        self.calls += 1
        return dict(self._raw)

    def forecast_next_hour(self, *, store_id, freq_min):
        self.calls += 1
        return dict(self._raw)


RAW_INSUFFICIENT = {
    "ok": True,
    "store": "ol_gangnam",
    "freq_min": 15,
    "data": [{"ts": "2026-08-19T23:00:00+09:00", "men_pred": 0.0, "women_pred": 0.0, "total_pred": 0.0}],
    "reasoning": {"signals": {}, "notes": ["履歴が足りません"]},
    "insufficient_history": True,
    "blend_w_ml": 0.5,
    "blended_slots": 1,
    "clamped_slots": 0,
}


@pytest.fixture
def app_client(monkeypatch):
    service = _FakeService(RAW_INSUFFICIENT)
    monkeypatch.setattr("oriental.routes.forecast._service", lambda: service)
    monkeypatch.setenv("ENABLE_FORECAST", "1")
    app = create_app()
    client = app.test_client()
    client._fake_service = service  # type: ignore[attr-defined]
    return client


def test_single_keeps_insufficient_history_after_multi_warmed_cache(app_client):
    """multi が先にキャッシュを温めても、単体は insufficient_history / reasoning を返す。"""
    multi = app_client.get("/api/forecast_today_multi?stores=gangnam")
    assert multi.status_code == 200

    single = app_client.get("/api/forecast_today?store=gangnam")
    assert single.status_code == 200
    body = single.get_json()
    assert body["ok"] is True
    assert body["insufficient_history"] is True
    assert body["reasoning"] == RAW_INSUFFICIENT["reasoning"]
    # キャッシュ共有そのものは維持されている（推論は 1 回だけ）
    assert app_client._fake_service.calls == 1


def test_multi_entry_shape_is_stable_regardless_of_who_warmed_cache(app_client):
    """single が先に温めても multi の by_slug の形は従来どおり（reasoning を含まない）。"""
    assert app_client.get("/api/forecast_today?store=gangnam").status_code == 200

    resp = app_client.get("/api/forecast_today_multi?stores=gangnam")
    assert resp.status_code == 200
    entry = resp.get_json()["by_slug"]["gangnam"]
    assert set(entry) == {"ok", "data", "blend_w_ml", "blended_slots", "clamped_slots"}
    assert entry["ok"] is True
    assert entry["blend_w_ml"] == 0.5
    assert app_client._fake_service.calls == 1


def test_multi_reports_error_entry_when_forecast_fails(app_client):
    """失敗時の by_slug エントリの形（ok:false / data:[] / error）が変わっていないこと。"""
    app_client._fake_service._raw = {"ok": False, "error": "model_unavailable"}
    resp = app_client.get("/api/forecast_today_multi?stores=gangnam")
    assert resp.status_code == 200
    body = resp.get_json()
    entry = body["by_slug"]["gangnam"]
    assert entry == {"ok": False, "data": [], "error": "model_unavailable"}
    assert body["errors_by_slug"] == {"gangnam": "model_unavailable"}
    assert body["partial_failure_count"] == 1
