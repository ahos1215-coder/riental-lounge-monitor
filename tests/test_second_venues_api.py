import os

import pytest

from oriental import create_app


class _FakeRepo:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    def get_by_store(self, store_id: str):
        return [
            {
                "name": "Bar A",
                "genre": "バー",
                "open_now": True,
                "weekday_text": ["Mon"],
                "lat": 35.0,
                "lng": 139.7,
                "address": "Somewhere",
                "place_id": "p1",
                "updated_at": "2024-01-01T00:00:00Z",
            }
        ]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "key")
    monkeypatch.setenv("DATA_BACKEND", "supabase")
    from oriental.routes import data as data_module

    monkeypatch.setattr(data_module, "SecondVenuesRepository", _FakeRepo)

    app = create_app()
    return app.test_client()


def test_second_venues_returns_rows(client):
    resp = client.get("/api/second_venues?store=nagasaki")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert isinstance(body["rows"], list)
    assert body["rows"][0]["place_id"] == "p1"
