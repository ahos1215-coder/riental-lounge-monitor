from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterable
import math

from ..clients.google_places import GooglePlacesClient, NearbyPlace, PlaceDetails
from ..data.second_venues_repository import SecondVenuesRepository
from ..domain.second_venues_genre import map_types_to_genre
from ..clients.google_places import classify_genre

MAX_SECOND_VENUES_RADIUS_M = 800  # 徒歩10分圏内の目安
MAX_SECOND_VENUES_PER_STORE = 15  # フロント表示件数（将来変更するかもしれない）


def update_all_second_venues(
    *,
    stores: Iterable[dict],
    google_client: GooglePlacesClient,
    repository: SecondVenuesRepository,
    logger: logging.Logger,
    pref_coords: dict[str, tuple[float, float]] | None = None,
    max_results: int = 15,
) -> dict[str, int]:
    store_list = list(stores)
    total_written = 0
    pref_coords = pref_coords or {}

    for store in store_list:
        store_id = store.get("store_id")
        if not store_id:
            logger.warning("update_second_venues.skip_no_store_id store=%s", store)
            continue

        lat, lng = _resolve_lat_lng(store, pref_coords=pref_coords)
        if lat is None or lng is None:
            logger.warning("update_second_venues.skip_no_coords store_id=%s", store_id)
            continue

        try:
            places = google_client.nearby_search(lat, lng)
        except Exception as exc:  # noqa: BLE001
            logger.exception("update_second_venues.nearby_failed store_id=%s", store_id)
            continue

        if not places:
            logger.info("update_second_venues.no_results store_id=%s", store_id)
            continue

        # 中心から近すぎる（同店舗扱い）ものを除外
        filtered_places: list[NearbyPlace] = []
        for p in places:
            try:
                dist = distance_m(lat, lng, p.lat, p.lng)
            except Exception:
                continue

            name_lower = (p.name or "").lower()
            if "oriental lounge" in name_lower or "オリエンタルラウンジ" in name_lower:
                continue

            # 中心から 50m 未満なら同一ビル扱いで除外
            if dist < 50:
                continue

            filtered_places.append(p)

        payloads = _build_payloads(
            places=filtered_places,
            google_client=google_client,
            logger=logger,
        )

        payloads = _select_second_venues_rows(
            store_id=store_id,
            store_lat=lat,
            store_lng=lng,
            rows=payloads,
            max_radius_m=MAX_SECOND_VENUES_RADIUS_M,
            max_total=MAX_SECOND_VENUES_PER_STORE,
        )

        if not payloads:
            logger.info("update_second_venues.no_selected_venues store_id=%s", store_id)
            continue

        try:
            written = repository.upsert_many(store_id, payloads)
            total_written += int(written) if written is not None else len(payloads)
        except Exception as exc:  # noqa: BLE001
            logger.exception("update_second_venues.upsert_failed store_id=%s", store_id)

    return {"total_venues": total_written, "stores": len(store_list)}


def run_update_second_venues_task(
    *,
    stores: Iterable[dict],
    pref_coords: dict[str, tuple[float, float]],
    google_api_key: str,
    supabase_url: str,
    supabase_key: str,
    session,
    logger: logging.Logger,
) -> dict[str, int]:
    if not google_api_key:
        logger.warning("update_second_venues.skip_no_google_api_key")
        return {"total_venues": 0, "stores": len(list(stores))}

    google_client = GooglePlacesClient(api_key=google_api_key, session=session, logger=logger)
    repository = SecondVenuesRepository(
        base_url=supabase_url,
        api_key=supabase_key,
        session=session,
        logger=logger,
    )

    return update_all_second_venues(
        stores=stores,
        google_client=google_client,
        repository=repository,
        logger=logger,
        pref_coords=pref_coords,
    )


def _build_payloads(
    *,
    places: list[NearbyPlace],
    google_client: GooglePlacesClient,
    logger: logging.Logger,
) -> list[dict]:
    out: list[dict] = []
    for place in places:
        details: PlaceDetails | None = None
        try:
            details = google_client.get_place_details(place.place_id)
        except Exception:  # noqa: BLE001
            logger.warning("update_second_venues.details_failed place_id=%s", place.place_id)

        # Nearby の name と Details の name を両方つなげてジャンル判定に使う
        raw_name_parts = []
        if place.name:
            raw_name_parts.append(place.name)
        if details and details.name:
            raw_name_parts.append(details.name)
        raw_name = " ".join(raw_name_parts)

        genre = classify_genre(
            raw_name,
            (details.types if details else None) or place.types,
        )
        now_iso = datetime.now(timezone.utc).isoformat()
        payload = {
            "place_id": place.place_id,
            "name": place.name,
            "lat": place.lat,
            "lng": place.lng,
            "genre": genre,
            "address": details.formatted_address if details else None,
            "open_now": details.open_now if details and details.open_now is not None else place.open_now,
            "weekday_text": details.weekday_text if details else None,
            "updated_at": now_iso,
        }
        out.append(payload)
    return out


def _resolve_lat_lng(
    store: dict,
    *,
    pref_coords: dict[str, tuple[float, float]],
) -> tuple[float | None, float | None]:
    lat = _to_float(_first_present(store, ("lat", "latitude")))
    lng = _to_float(_first_present(store, ("lng", "lon", "longitude")))
    if lat is not None and lng is not None:
        return lat, lng

    pref = store.get("pref")
    if pref and pref in pref_coords:
        coords = pref_coords[pref]
        if isinstance(coords, tuple) and len(coords) == 2:
            pref_lat, pref_lng = coords
            return _to_float(pref_lat), _to_float(pref_lng)

    return None, None


def _first_present(store: dict, keys: tuple[str, ...]):
    for key in keys:
        value = store.get(key)
        if value is not None:
            return value
    return None


def _to_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """2点間の距離をおおよそメートルで返す（Haversine 近似）。"""
    R = 6371000.0  # 地球半径[m]
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """2点の緯度経度から距離(m)をざっくり計算する。"""
    r = 6371000.0  # 地球半径 (m)
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c


def _guess_second_venue_category(name: str, genre: str) -> str | None:
    """店名や genre 文字列からざっくりカテゴリを推定する。"""
    text = f"{name} {genre}".lower()

    if "カラオケ" in text or "karaoke" in text:
        return "karaoke"

    if "ダーツ" in text or "darts" in text:
        return "darts_bar"

    if "ラブホテル" in text or "ラブホ" in text:
        return "love_hotel"

    if "ラーメン" in text or "らーめん" in text or "ramen" in text:
        return "ramen"

    return None


def _select_second_venues_rows(
    store_id: str,
    store_lat: float,
    store_lng: float,
    rows: list[dict],
    *,
    max_radius_m: int,
    max_total: int,
) -> list[dict]:
    """
    Nearby Search の rows から指定半径内かつカテゴリ限定で最大件数まで絞り込む。
    """
    categories = ("karaoke", "darts_bar", "love_hotel", "ramen")
    buckets: dict[str, list[dict]] = {c: [] for c in categories}
    nearby_candidates: list[tuple[float, dict]] = []

    for row in rows:
        lat = row.get("lat")
        lng = row.get("lng")
        if lat is None or lng is None:
            continue

        try:
            dist = _haversine_m(float(store_lat), float(store_lng), float(lat), float(lng))
        except Exception:
            continue

        if dist > max_radius_m:
            continue

        name = str(row.get("name") or "")
        genre = str(row.get("genre") or "")

        # 自店舗 (ORIENTAL LOUNGE) は除外
        if "oriental lounge" in name.lower():
            continue

        cat = _guess_second_venue_category(name, genre)
        if cat in categories:
            buckets[cat].append({"_dist": dist, **row})

        nearby_candidates.append((dist, row))

    for cat in categories:
        buckets[cat].sort(key=lambda r: r["_dist"])

    selected: list[dict] = []
    while len(selected) < max_total and any(buckets[c] for c in categories):
        for cat in categories:
            bucket = buckets[cat]
            if not bucket:
                continue
            row = bucket.pop(0)
            row.pop("_dist", None)
            selected.append(row)
            if len(selected) >= max_total:
                break

    if not selected and nearby_candidates:
        nearby_candidates.sort(key=lambda t: t[0])
        selected = [row for _, row in nearby_candidates[:max_total]]

    return selected
