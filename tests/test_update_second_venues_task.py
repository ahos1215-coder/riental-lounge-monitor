from oriental.clients.google_places import NearbyPlace, PlaceDetails
from oriental.domain.second_venues_genre import map_types_to_genre
from oriental.tasks.update_second_venues import update_all_second_venues


class _FakeLogger:
    def __init__(self):
        self.messages = []

    def info(self, *args, **kwargs):
        self.messages.append(("info", args))

    def warning(self, *args, **kwargs):
        self.messages.append(("warning", args))

    def exception(self, *args, **kwargs):
        self.messages.append(("exception", args))


class _FakeRepository:
    def __init__(self):
        self.calls = []

    def upsert_many(self, store_id, payloads):
        self.calls.append((store_id, payloads))


class _FakeGoogleClient:
    def __init__(self):
        self.nearby_calls = []
        self.detail_calls = []

    def nearby_search(self, lat, lng):
        self.nearby_calls.append((lat, lng))
        return [
            NearbyPlace(
                place_id="p1",
                name="Bar A",
                lat=lat + 0.001,
                lng=lng + 0.001,
                types=["bar"],
                open_now=True,
            ),
            NearbyPlace(
                place_id="p2",
                name="Club B",
                lat=lat + 0.002,
                lng=lng + 0.002,
                types=["night_club"],
                open_now=None,
            ),
        ]

    def get_place_details(self, place_id: str):
        self.detail_calls.append(place_id)
        if place_id == "p1":
            return PlaceDetails(
                place_id="p1",
                name="Bar A",
                formatted_address="Addr 1",
                weekday_text=["Mon"],
                open_now=False,
                types=["bar", "food"],
            )
        raise RuntimeError("details failed")


def test_update_all_second_venues_builds_payload_and_upserts():
    stores = [{"store_id": "ol_shibuya", "pref": "tokyo"}]
    pref_coords = {"tokyo": (35.0, 139.0)}
    repo = _FakeRepository()
    client = _FakeGoogleClient()
    logger = _FakeLogger()

    summary = update_all_second_venues(
        stores=stores,
        google_client=client,
        repository=repo,
        logger=logger,
        pref_coords=pref_coords,
        max_results=5,
    )

    assert summary["total_venues"] == 2
    assert summary["stores"] == 1

    assert repo.calls[0][0] == "ol_shibuya"
    payloads = repo.calls[0][1]
    assert len(payloads) == 2
    assert payloads[0]["genre"] == "バー"
    assert payloads[0]["address"] == "Addr 1"
    assert payloads[1]["genre"] == "バー"
    assert payloads[1]["address"] is None
    assert payloads[1]["open_now"] is None
    assert isinstance(payloads[0]["updated_at"], str)

    assert client.nearby_calls[0] == (35.0, 139.0)
    assert set(client.detail_calls) == {"p1", "p2"}


def test_map_types_to_genre_precedence():
    assert map_types_to_genre(["karaoke", "bar"]) == "カラオケ"
    assert map_types_to_genre(["pub"]) == "バー"
    assert map_types_to_genre(["lodging"]) == "ホテル"
    assert map_types_to_genre(["restaurant"]) == "居酒屋"
    assert map_types_to_genre(["night_club"]) == "クラブ / ライブバー"
    assert map_types_to_genre(["unknown"]) == "その他"
