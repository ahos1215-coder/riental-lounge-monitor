from oriental import create_app
from oriental.config import AppConfig


def test_api_meta_returns_config_summary(monkeypatch):
    # set minimal env to ensure supabase keys and backend choice are visible
    monkeypatch.setenv("DATA_BACKEND", "supabase")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "dummy-key")
    monkeypatch.setenv("STORE_ID", "ol_test_store_meta")

    app = create_app(AppConfig.from_env())
    client = app.test_client()

    resp = client.get("/api/meta")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body.get("ok") is True
    data = body.get("data", {})

    assert data.get("data_backend") in ("supabase", "legacy")
    supa = data.get("supabase", {})
    assert "url" in supa
    assert "service_role" in supa
    assert supa.get("store_id") == "ol_test_store_meta"

    # basic runtime fields
    assert "timezone" in data
    assert "window" in data and "start" in data["window"] and "end" in data["window"]
    assert "http_timeout" in data
    assert "http_retry" in data
    assert "max_range_limit" in data
