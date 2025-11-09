from oriental import create_app


def test_range_limit_zero_is_clamped_to_one():
    app = create_app()
    client = app.test_client()
    resp = client.get("/api/range?limit=0")
    assert resp.status_code == 200
    body = resp.get_json()
    assert isinstance(body.get("rows"), list)


def test_range_limit_too_large_is_clamped_to_max():
    app = create_app()
    client = app.test_client()
    resp = client.get("/api/range?limit=120000")
    assert resp.status_code == 200


def test_invalid_from_date_returns_422():
    app = create_app()
    client = app.test_client()
    resp = client.get("/api/range?from=2024-13-01")
    assert resp.status_code == 422


def test_from_after_to_returns_422():
    app = create_app()
    client = app.test_client()
    resp = client.get("/api/range?from=2024-11-10&to=2024-11-01")
    assert resp.status_code == 422
