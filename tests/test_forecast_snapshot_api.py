"""/api/forecast_snapshot のテスト。

完了済みの夜（昨日/先週/カスタムの過去日、または「今日」モードで夜が既に終わった
ケース）向けに、その夜へ実際に配信されていた予測（scripts/snapshot_forecasts.py が
毎晩 ~18:10 JST に Supabase Storage へ保存するスナップショット）を返すエンドポイント。

/api/forecast_accuracy の `_fetch_live_accuracy` と同じ `_storage_get` ヘルパーを
共有しているため、Storage 未設定・404・壊れたJSON いずれのケースでも
例外を外に漏らさず ok:false・HTTP 200 にフォールバックすることを確認する。
"""

from __future__ import annotations

import json
import urllib.error

import pytest

from oriental import create_app


class _FakeHTTPResponse:
    def __init__(self, body: bytes):
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def app_client(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "key")
    monkeypatch.setenv("DATA_BACKEND", "supabase")
    app = create_app()
    return app.test_client()


def _mock_urlopen_returns(monkeypatch, payload: dict | None, http_error_code: int | None = None):
    def _fake_urlopen(req, timeout=10):
        if http_error_code is not None:
            raise urllib.error.HTTPError(
                req.full_url if hasattr(req, "full_url") else "https://example",
                http_error_code,
                "not found",
                {},
                None,
            )
        return _FakeHTTPResponse(json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)


def test_invalid_store_returns_400(app_client):
    resp = app_client.get("/api/forecast_snapshot?store=not-a-real-store&date=20260708")
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["ok"] is False
    assert body["error"] == "invalid-store"


@pytest.mark.parametrize("bad_date", ["2026-07-08", "2026078", "", "abcdefgh", "202607081"])
def test_invalid_date_returns_400(app_client, bad_date):
    resp = app_client.get(f"/api/forecast_snapshot?store=nagasaki&date={bad_date}")
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["ok"] is False
    assert body["error"] == "invalid-date"


def test_missing_snapshot_file_returns_ok_false_200(app_client, monkeypatch):
    _mock_urlopen_returns(monkeypatch, payload=None, http_error_code=404)
    resp = app_client.get("/api/forecast_snapshot?store=nagasaki&date=20260101")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body == {"ok": False, "date": "20260101", "data": []}


def test_store_missing_from_by_slug_returns_ok_false_200(app_client, monkeypatch):
    # スナップショット自体はあるが、この店舗のデータが無い（新規追加店舗など）。
    _mock_urlopen_returns(
        monkeypatch,
        payload={"night_date": "20260708", "by_slug": {"other_store": [{"ts": "x"}]}},
    )
    resp = app_client.get("/api/forecast_snapshot?store=nagasaki&date=20260708")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body == {"ok": False, "date": "20260708", "data": []}


def test_success_returns_store_points(app_client, monkeypatch):
    points = [
        {"ts": "2026-07-08T19:00:00+09:00", "total_pred": 30, "men_pred": 12, "women_pred": 18},
        {"ts": "2026-07-08T19:15:00+09:00", "total_pred": 32, "men_pred": 13, "women_pred": 19},
    ]
    _mock_urlopen_returns(
        monkeypatch,
        payload={"night_date": "20260708", "by_slug": {"nagasaki": points}},
    )
    resp = app_client.get("/api/forecast_snapshot?store=nagasaki&date=20260708")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["date"] == "20260708"
    assert body["data"] == points


def test_success_sets_long_immutable_cache_header(app_client, monkeypatch):
    _mock_urlopen_returns(
        monkeypatch,
        payload={"night_date": "20260708", "by_slug": {"nagasaki": [{"ts": "x"}]}},
    )
    resp = app_client.get("/api/forecast_snapshot?store=nagasaki&date=20260708")
    cache_control = resp.headers.get("Cache-Control", "")
    assert "s-maxage=86400" in cache_control
    assert "stale-while-revalidate=604800" in cache_control


def test_malformed_json_falls_back_to_ok_false(app_client, monkeypatch):
    def _fake_urlopen(req, timeout=10):
        return _FakeHTTPResponse(b"not valid json{{{")

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    resp = app_client.get("/api/forecast_snapshot?store=nagasaki&date=20260708")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body == {"ok": False, "date": "20260708", "data": []}


def test_aisekiya_slug_accepted(app_client, monkeypatch):
    """相席屋の slug (ay_*) も店舗レジストリに含まれる（ol_ 接頭辞なし）ので通ること。"""
    _mock_urlopen_returns(
        monkeypatch,
        payload={"night_date": "20260708", "by_slug": {"ay_shibuya": [{"ts": "x"}]}},
    )
    resp = app_client.get("/api/forecast_snapshot?store=ay_shibuya&date=20260708")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["data"] == [{"ts": "x"}]
