from datetime import datetime

import pytest

from oriental import create_app


@pytest.fixture()
def client():
    app = create_app()
    return app.test_client()


def test_collect_invalid_payloads(client):
    # Missing required store
    resp = client.post("/tasks/collect", json={"men": 10, "women": 5, "ts": datetime.now().isoformat()})
    assert resp.status_code == 400

    # Invalid types
    resp = client.post("/tasks/collect", json={"store": 123, "men": "a", "women": 2, "ts": datetime.now().isoformat()})
    assert resp.status_code == 400

    # Missing timezone in ts
    resp = client.post("/tasks/collect", json={"store": "nagasaki", "men": 1, "women": 2, "ts": "2024-11-08T21:15:00"})
    assert resp.status_code == 400


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
    resp = client.post("/tasks/collect", json=payload)
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
    )
    assert resp.status_code == 400
