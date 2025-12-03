from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Iterable

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

NEARBY_ENDPOINT = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
DETAILS_ENDPOINT = "https://maps.googleapis.com/maps/api/place/details/json"
DEFAULT_TYPE_FILTERS = [
    "bar",
    "pub",
    "lodging",
    "restaurant",
    "food",
    "night_club",
    "karaoke",
]

KARAOKE_KEYWORDS = ["カラオケ", "karaoke"]
DARTS_KEYWORDS = ["ダーツ", "darts", "Darts"]
RAMEN_KEYWORDS = ["ラーメン", "ramen", "ラ-メン"]
LOVEHOTEL_KEYWORDS = ["ラブホテル", "ラブホ", "HOTEL", "ホテル"]


def classify_genre(name: str, types: list[str] | None) -> str:
    """Google Places の name / types から MEGRIBI 用ジャンルを決める。"""
    types = [t.lower() for t in (types or [])]
    type_set = set(types)
    lname = (name or "").lower()

    # ラブホ（lodging + それっぽい名前）
    if "lodging" in type_set:
        for kw in LOVEHOTEL_KEYWORDS:
            if kw.lower() in lname:
                return "ラブホ"

    # ラーメン（名前キーワード + 飲食系 type）
    if any(kw.lower() in lname for kw in RAMEN_KEYWORDS) and (
        "restaurant" in type_set or "food" in type_set
    ):
        return "ラーメン"

    # カラオケ（名前キーワード or types に karaoke）
    if "karaoke" in type_set or any(kw.lower() in lname for kw in KARAOKE_KEYWORDS):
        return "カラオケ"

    # ダーツバー（名前キーワード or types に darts）
    if "darts" in type_set or any(kw.lower() in lname for kw in DARTS_KEYWORDS):
        return "ダーツバー"

    # それ以外はとりあえずバー扱い
    return "バー"

class GooglePlacesError(RuntimeError):
    pass


@dataclass(slots=True)
class NearbyPlace:
    place_id: str
    name: str
    lat: float
    lng: float
    types: list[str]
    open_now: bool | None


@dataclass(slots=True)
class PlaceDetails:
    place_id: str
    name: str | None
    formatted_address: str | None
    weekday_text: list[str] | None
    open_now: bool | None
    types: list[str]


class GooglePlacesClient:
    def __init__(
        self,
        api_key: str,
        *,
        session: requests.Session | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.api_key = api_key
        self.session = session or requests.Session()
        self.logger = logger or logging.getLogger(__name__)
        retry = Retry(total=3, backoff_factor=0.6, status_forcelist=(429, 500, 502, 503, 504))
        adapter = HTTPAdapter(max_retries=retry)
        if hasattr(self.session, "mount"):
            self.session.mount("http://", adapter)
            self.session.mount("https://", adapter)

    def nearby_search(
        self,
        lat: float,
        lng: float,
        *,
        radius: int = 800,
        type_filters: list[str] | None = None,
    ) -> list[NearbyPlace]:
        self._ensure_api_key()
        params = {
            "key": self.api_key,
            "location": f"{lat},{lng}",
            "radius": int(radius),
            "language": "ja",
        }
        filters = type_filters if type_filters is not None else DEFAULT_TYPE_FILTERS
        if filters:
            params["keyword"] = " ".join(filters)

        resp = self.session.get(NEARBY_ENDPOINT, params=params, timeout=12)
        payload = self._parse_response(resp, "nearby_search")

        status = payload.get("status")
        if status not in {"OK", "ZERO_RESULTS"}:
            raise GooglePlacesError(f"nearby_search failed with status {status}")

        results = payload.get("results", [])
        if not isinstance(results, list):
            return []

        places: list[NearbyPlace] = []
        for item in results:
            decoded = _decode_nearby(item)
            if decoded:
                places.append(decoded)

        self.logger.info("google_places.nearby_ok count=%d", len(places))
        return places

    def get_place_details(self, place_id: str) -> PlaceDetails | None:
        self._ensure_api_key()
        params = {
            "key": self.api_key,
            "place_id": place_id,
            "language": "ja",
            "fields": "formatted_address,opening_hours,types,place_id,name",
        }
        resp = self.session.get(DETAILS_ENDPOINT, params=params, timeout=12)
        payload = self._parse_response(resp, "place_details")

        status = payload.get("status")
        if status == "ZERO_RESULTS":
            return None
        if status and status != "OK":
            raise GooglePlacesError(f"place_details failed with status {status}")

        result = payload.get("result", {})
        if not isinstance(result, dict):
            return None
        return _decode_details(result, place_id=place_id)

    def _ensure_api_key(self) -> None:
        if not self.api_key:
            raise GooglePlacesError("GOOGLE_PLACES_API_KEY is not set")

    def _parse_response(self, resp: requests.Response, action: str) -> dict[str, Any]:
        if not resp.ok:
            raise GooglePlacesError(f"{action} failed with status {resp.status_code}")
        try:
            payload = resp.json()
        except ValueError as exc:  # pragma: no cover - defensive
            raise GooglePlacesError("invalid JSON from Google Places") from exc
        if not isinstance(payload, dict):
            raise GooglePlacesError("unexpected payload type from Google Places")
        return payload


def _decode_nearby(item: Any) -> NearbyPlace | None:
    if not isinstance(item, dict):
        return None
    place_id = item.get("place_id")
    name = item.get("name")
    geometry = item.get("geometry") if isinstance(item.get("geometry"), dict) else {}
    location = geometry.get("location", {}) if isinstance(geometry, dict) else {}
    lat = _to_float(location.get("lat"))
    lng = _to_float(location.get("lng"))
    if not place_id or not name or lat is None or lng is None:
        return None
    types = _string_list(item.get("types"))
    open_now = _extract_open_now(item.get("opening_hours"))
    return NearbyPlace(
        place_id=str(place_id),
        name=str(name),
        lat=lat,
        lng=lng,
        types=types,
        open_now=open_now,
    )


def _decode_details(result: dict[str, Any], *, place_id: str) -> PlaceDetails:
    formatted_address = result.get("formatted_address")
    opening_hours = result.get("opening_hours") if isinstance(result.get("opening_hours"), dict) else None
    weekday_text = opening_hours.get("weekday_text") if isinstance(opening_hours, dict) else None
    weekday = _string_list(weekday_text)
    open_now = _extract_open_now(opening_hours)
    types = _string_list(result.get("types"))
    name = result.get("name")

    return PlaceDetails(
        place_id=str(place_id),
        name=str(name) if name is not None else None,
        formatted_address=str(formatted_address) if formatted_address is not None else None,
        weekday_text=weekday,
        open_now=open_now,
        types=types,
    )


def _extract_open_now(opening_hours: Any) -> bool | None:
    if not isinstance(opening_hours, dict):
        return None
    value = opening_hours.get("open_now")
    return bool(value) if isinstance(value, bool) else None


def _string_list(raw: Any) -> list[str]:
    if not isinstance(raw, Iterable) or isinstance(raw, (str, bytes)):
        return []
    out: list[str] = []
    for item in raw:
        if item is None:
            continue
        out.append(str(item))
    return out


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
