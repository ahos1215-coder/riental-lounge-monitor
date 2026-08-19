from datetime import date

from oriental import create_app
from oriental.routes.data_range import _parse_range_query


def _parse(query: str):
    """/api/range のクエリ文字列を実際のリクエストコンテキストで解釈する。"""
    app = create_app()
    with app.test_request_context(f"/api/range{query}"):
        return _parse_range_query(app.config["APP_CONFIG"])


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


# --- from/to の片方だけ指定したときの期間フィルタ（2026-08-19 修正の回帰テスト） ---
#
# 下流は start と end が両方揃っているときだけ期間フィルタを効かせるため、
# `to` だけを指定すると条件が黙って無視され「最新 N 件」が返っていた。
# `from` だけの場合（その1日分）と揃えて、`to` だけでも1日分として効かせる。


def test_from_only_is_a_single_day_window():
    query = _parse("?from=2024-11-05")
    assert query.start == date(2024, 11, 5)
    assert query.end == date(2024, 11, 5)


def test_to_only_is_not_silently_ignored():
    query = _parse("?to=2024-11-05")
    assert query.start == date(2024, 11, 5)
    assert query.end == date(2024, 11, 5)


def test_both_from_and_to_are_preserved():
    query = _parse("?from=2024-11-01&to=2024-11-05")
    assert query.start == date(2024, 11, 1)
    assert query.end == date(2024, 11, 5)


def test_no_date_params_keeps_latest_n_behaviour():
    query = _parse("?limit=10")
    assert query.start is None
    assert query.end is None
    assert query.limit == 10


def test_to_only_request_still_returns_200():
    app = create_app()
    client = app.test_client()
    resp = client.get("/api/range?to=2024-11-05")
    assert resp.status_code == 200
