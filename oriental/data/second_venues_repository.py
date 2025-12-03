from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .provider import SupabaseError


@dataclass(slots=True)
class SecondVenue:
    place_id: str
    name: str
    lat: float
    lng: float
    genre: str | None = None
    address: str | None = None
    open_now: bool | None = None
    weekday_text: list[str] | None = None
    updated_at: str | None = None


class SecondVenuesRepository:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        session: requests.Session | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/") if base_url else ""
        self.api_key = api_key
        self.endpoint = f"{self.base_url}/rest/v1/second_venues" if self.base_url else ""
        self.session = session or requests.Session()
        self.logger = logger or logging.getLogger(__name__)
        retry = Retry(total=3, backoff_factor=0.6, status_forcelist=(429, 500, 502, 503, 504))
        adapter = HTTPAdapter(max_retries=retry)
        if hasattr(self.session, "mount"):
            self.session.mount("http://", adapter)
            self.session.mount("https://", adapter)

    def get_by_store(self, store_id: str) -> list[SecondVenue]:
        self._ensure_configured()
        params: list[tuple[str, str]] = [
            ("select", "name,lat,lng,genre,address,open_now,weekday_text,updated_at,place_id"),
            ("store_id", f"eq.{store_id}"),
            ("order", "updated_at.desc"),
        ]
        headers = self._auth_headers()

        try:
            resp = self.session.get(self.endpoint, params=params, headers=headers, timeout=12)
        except Exception as exc:  # noqa: BLE001
            raise SupabaseError("supabase request failed") from exc

        if not resp.ok:
            raise SupabaseError(f"supabase returned status {resp.status_code}")

        try:
            payload = resp.json()
        except ValueError as exc:  # pragma: no cover - defensive
            raise SupabaseError("supabase returned invalid JSON") from exc

        if not isinstance(payload, list):
            raise SupabaseError("supabase payload is not a list")

        venues: list[SecondVenue] = []
        for row in payload:
            if not isinstance(row, dict):
                continue
            decoded = _decode_venue(row)
            if decoded:
                venues.append(decoded)

        self.logger.info("second_venues.get_by_store_ok store_id=%s returned=%d", store_id, len(venues))
        return venues

    def upsert_many(self, store_id: str, venues: list[dict]) -> int:
        self._ensure_configured()
        if not venues:
            self.logger.info("second_venues.upsert_many.skip_empty store_id=%s", store_id)
            return 0

        payload: list[dict[str, Any]] = []
        now_iso = datetime.now(timezone.utc).isoformat()
        for row in venues:
            if not isinstance(row, dict):
                continue
            normalized = _normalise_for_upsert(row, store_id=store_id, fallback_updated_at=now_iso)
            if normalized:
                payload.append(normalized)

        if not payload:
            self.logger.info("second_venues.upsert_many.skip_invalid store_id=%s", store_id)
            return 0

        headers = self._auth_headers(content_type=True)
        headers["Prefer"] = "resolution=merge-duplicates,return=representation"
        params = [("on_conflict", "store_id,place_id")]

        try:
            resp = self.session.post(
                self.endpoint, params=params, json=payload, headers=headers, timeout=12
            )
        except Exception as exc:  # noqa: BLE001
            raise SupabaseError("supabase request failed") from exc

        if not resp.ok:
            raise SupabaseError(f"supabase returned status {resp.status_code}")

        self.logger.info("second_venues.upsert_many_ok store_id=%s count=%d", store_id, len(payload))
        return len(payload)

    def _auth_headers(self, *, content_type: bool = False) -> dict[str, str]:
        headers = {
            "apikey": self.api_key,
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }
        if content_type:
            headers["Content-Type"] = "application/json"
        return headers

    def _ensure_configured(self) -> None:
        if not self.endpoint or not self.api_key:
            raise SupabaseError("supabase is not configured")


def _decode_venue(row: dict[str, Any]) -> SecondVenue | None:
    place_id = row.get("place_id")
    name = row.get("name")
    lat = _to_float(row.get("lat"))
    lng = _to_float(row.get("lng"))
    if not place_id or not name or lat is None or lng is None:
        return None

    return SecondVenue(
        place_id=str(place_id),
        name=str(name),
        lat=lat,
        lng=lng,
        genre=_to_optional_str(row.get("genre")),
        address=_to_optional_str(row.get("address")),
        open_now=_to_optional_bool(row.get("open_now")),
        weekday_text=_normalise_weekday_text(row.get("weekday_text")),
        updated_at=_normalise_updated_at(row.get("updated_at")),
    )


def _normalise_for_upsert(
    row: dict[str, Any],
    *,
    store_id: str,
    fallback_updated_at: str,
) -> dict[str, Any] | None:
    place_id = row.get("place_id")
    name = row.get("name")
    lat = _to_float(row.get("lat"))
    lng = _to_float(row.get("lng"))
    if not place_id or not name or lat is None or lng is None:
        return None

    return {
        "store_id": store_id,
        "place_id": str(place_id),
        "name": str(name),
        "lat": lat,
        "lng": lng,
        "genre": _to_optional_str(row.get("genre")),
        "address": _to_optional_str(row.get("address")),
        "open_now": _to_optional_bool(row.get("open_now")),
        "weekday_text": _normalise_weekday_text(row.get("weekday_text")),
        "updated_at": _normalise_updated_at(row.get("updated_at")) or fallback_updated_at,
    }


def _normalise_weekday_text(raw: Any) -> list[str] | None:
    if raw is None:
        return None
    if isinstance(raw, list):
        out = [str(item) for item in raw if item is not None]
        return out or None
    return [str(raw)]


def _normalise_updated_at(raw: Any) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.astimezone(timezone.utc).isoformat()
    return str(raw)


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


def _to_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    value_str = str(value).strip()
    return value_str if value_str else None
