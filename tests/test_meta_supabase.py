from oriental import create_app
from oriental.config import AppConfig


def test_meta_includes_supabase_settings(monkeypatch):
    monkeypatch.setenv("ENABLE_FORECAST", "1")
    monkeypatch.setenv("DATA_BACKEND", "supabase")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-service-key")
    monkeypatch.setenv("STORE_ID", "ol_test_store")

    app = create_app(AppConfig.from_env())
    client = app.test_client()

    resp = client.get("/api/meta")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body.get("ok") is True
    data = body.get("data", {})
    assert data.get("data_backend") == "supabase"
    assert data.get("supabase", {}).get("store_id") == "ol_test_store"
