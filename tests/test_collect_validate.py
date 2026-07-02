import os
from datetime import datetime

import pytest

from oriental import create_app


@pytest.fixture()
def client():
    app = create_app()
    return app.test_client()


def _auth_headers():
    """/tasks/collect は CRON_SECRET 設定時に Bearer 認証を要求する。
    設定されていれば正しいトークンを付ける（ローカル .env.local 等）。
    未設定（CI/デフォルト）ならヘッダー不要で従来どおり通る。"""
    secret = os.getenv("CRON_SECRET", "").strip()
    return {"Authorization": f"Bearer {secret}"} if secret else {}


def test_collect_invalid_payloads(client):
    h = _auth_headers()
    # Missing required store
    resp = client.post("/tasks/collect", json={"men": 10, "women": 5, "ts": datetime.now().isoformat()}, headers=h)
    assert resp.status_code == 400

    # Invalid types
    resp = client.post("/tasks/collect", json={"store": 123, "men": "a", "women": 2, "ts": datetime.now().isoformat()}, headers=h)
    assert resp.status_code == 400

    # Missing timezone in ts
    resp = client.post("/tasks/collect", json={"store": "nagasaki", "men": 1, "women": 2, "ts": "2024-11-08T21:15:00"}, headers=h)
    assert resp.status_code == 400


def test_collect_requires_auth_when_secret_set(client, monkeypatch):
    # CRON_SECRET 設定時、正しい Bearer トークンが無いリクエストは 401。
    monkeypatch.setenv("CRON_SECRET", "unit-test-secret")
    resp = client.post(
        "/tasks/collect",
        json={"store": "nagasaki", "men": 1, "women": 2, "ts": "2024-11-08T21:15:00+09:00"},
    )
    assert resp.status_code == 401


def test_collect_valid_payload(client, monkeypatch):
    called = {}

    def fake_append_row(self, payload):
        called["payload"] = payload

    from oriental.clients import gas_client

    monkeypatch.setattr(gas_client.GasClient, "append_row", fake_append_row)

    payload = {
        "store": "nagasaki",
        "men": 12,
        "women": 8,
        "ts": "2024-11-08T21:15:00+09:00",
    }
    resp = client.post("/tasks/collect", json=payload, headers=_auth_headers())
    assert resp.status_code == 200
    assert called


def test_collect_invalid_ts_from_query(client):
    resp = client.get(
        "/tasks/collect",
        query_string={
            "store": "nagasaki",
            "men": 5,
            "women": 3,
            "ts": "2024-11-08T21:15:00",
        },
        headers=_auth_headers(),
    )
    assert resp.status_code == 400
