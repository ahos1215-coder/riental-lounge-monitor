from datetime import datetime, timezone

from oriental.data.second_venues_repository import SecondVenue, SecondVenuesRepository


class _FakeResponse:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, payload):
        self.payload = payload
        self.last_params = None
        self.last_headers = None
        self.last_url = None
        self.last_timeout = None
        self.last_json = None

    def mount(self, *_args, **_kwargs):
        return None

    def get(self, url, *, params=None, headers=None, timeout=None):
        self.last_url = url
        self.last_params = params
        self.last_headers = headers
        self.last_timeout = timeout
        return _FakeResponse(200, self.payload)

    def post(self, url, *, params=None, json=None, headers=None, timeout=None):
        self.last_url = url
        self.last_params = params
        self.last_headers = headers
        self.last_timeout = timeout
        self.last_json = json
        return _FakeResponse(201, self.payload)


def test_get_by_store_returns_normalised_dataclasses():
    payload = [
        {
            "store_id": "ol_test",
            "place_id": "place-1",
            "name": "Bar A",
            "lat": "35.0",
            "lng": 139.7,
            "genre": "bar",
            "address": "Somewhere",
            "open_now": True,
            "weekday_text": ["Mon", "Tue"],
            "updated_at": datetime(2024, 1, 1, tzinfo=timezone.utc),
        },
        {"store_id": "ol_test", "place_id": None, "name": "skip me"},
    ]
    session = _FakeSession(payload)
    repo = SecondVenuesRepository(
        base_url="https://example.supabase.co",
        api_key="test-key",
        session=session,
    )

    venues = repo.get_by_store("ol_test")

    assert len(venues) == 1
    assert isinstance(venues[0], SecondVenue)
    assert venues[0].place_id == "place-1"
    assert venues[0].lat == 35.0
    assert ("store_id", "eq.ol_test") in session.last_params
    assert session.last_url.endswith("/rest/v1/second_venues")


def test_upsert_many_sends_conflict_keys_and_payload():
    session = _FakeSession([])
    repo = SecondVenuesRepository(
        base_url="https://example.supabase.co",
        api_key="test-key",
        session=session,
    )
    venues = [
        {
            "place_id": "place-1",
            "name": "Bar A",
            "lat": "35.0",
            "lng": 139.7,
            "genre": "bar",
            "address": "Somewhere",
            "open_now": False,
            "weekday_text": ["Mon", "Tue"],
            "updated_at": "2024-01-01T00:00:00Z",
        },
        {
            # Missing place_id -> skipped
            "name": "invalid",
            "lat": 1,
            "lng": 2,
        },
    ]

    repo.upsert_many("ol_test", venues)

    assert session.last_url.endswith("/rest/v1/second_venues")
    assert session.last_params == [("on_conflict", "store_id,place_id")]
    assert session.last_headers["Prefer"].startswith("resolution=merge-duplicates")
    assert isinstance(session.last_json, list)
    assert len(session.last_json) == 1
    sent = session.last_json[0]
    assert sent["store_id"] == "ol_test"
    assert sent["place_id"] == "place-1"
    assert sent["weekday_text"] == ["Mon", "Tue"]
