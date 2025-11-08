from oriental import create_app


def test_healthz_ok():
    app = create_app()
    client = app.test_client()
    resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body and body.get("ok") is True
