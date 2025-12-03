import pytest

from oriental.clients.google_places import GooglePlacesClient, GooglePlacesError


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
    def __init__(self, nearby_status: str = "OK", details_status: str = "OK"):
        self.nearby_status = nearby_status
        self.details_status = details_status
        self.last_params = None
        self.last_url = None
        self.last_timeout = None

    def mount(self, *_args, **_kwargs):
        return None

    def get(self, url, *, params=None, timeout=None):
        self.last_url = url
        self.last_params = params
        self.last_timeout = timeout
        if "nearbysearch" in url:
            results = []
            if self.nearby_status == "OK":
                results = [
                    {
                        "place_id": "place-1",
                        "name": "Bar A",
                        "geometry": {"location": {"lat": 35.1, "lng": 139.8}},
                        "types": ["bar", "food"],
                        "opening_hours": {"open_now": True},
                    }
                ]
            payload = {
                "status": self.nearby_status,
                "results": results,
            }
            return _FakeResponse(200, payload)
        payload = {
            "status": self.details_status,
            "result": {
                "place_id": "place-1",
                "name": "Bar A",
                "formatted_address": "Somewhere 1-2-3",
                "opening_hours": {"weekday_text": ["Mon", "Tue"], "open_now": False},
                "types": ["bar", "food"],
            },
        }
        return _FakeResponse(200, payload)


def test_nearby_and_details_are_normalised():
    session = _FakeSession()
    client = GooglePlacesClient(api_key="key", session=session)

    places = client.nearby_search(35.0, 139.7, radius=500, type_filters=["bar", "night_club"])
    assert len(places) == 1
    assert places[0].place_id == "place-1"
    assert places[0].open_now is True
    assert session.last_params["keyword"] == "bar night_club"
    assert session.last_params["radius"] == 500
    assert "nearbysearch" in session.last_url

    details = client.get_place_details("place-1")
    assert details.formatted_address == "Somewhere 1-2-3"
    assert details.weekday_text == ["Mon", "Tue"]
    assert details.open_now is False
    assert "details" in session.last_url


def test_zero_results_and_error_handling():
    session = _FakeSession(nearby_status="ZERO_RESULTS", details_status="ZERO_RESULTS")
    client = GooglePlacesClient(api_key="key", session=session)

    places = client.nearby_search(35.0, 139.7)
    assert places == []

    assert client.get_place_details("missing") is None

    session_error = _FakeSession(nearby_status="OVER_QUERY_LIMIT")
    client_error = GooglePlacesClient(api_key="key", session=session_error)
    with pytest.raises(GooglePlacesError):
        client_error.nearby_search(0, 0)
