from oriental import create_app


def test_range_limit_zero_returns_422():
    app = create_app()
    client = app.test_client()
    resp = client.get("/api/range?limit=0")
    assert resp.status_code == 422
    body = resp.get_json()
    assert body["error"] == "invalid-parameters"
