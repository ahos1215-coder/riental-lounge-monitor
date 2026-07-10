"""Unit tests for scripts/warm_cdn_local.py's pure URL-building functions.

These assert the built warm URLs byte-match known-good literals derived by
hand from the client code (storePreviewSnapshot.ts / stores-list-client.tsx /
StorePageClient.tsx / home-client.tsx) — see the module docstring in
warm_cdn_local.py for the exact source references. No network access.
"""

from __future__ import annotations

import math
from datetime import datetime

import pytest

import scripts.warm_cdn_local as warm

JST = warm.JST


def test_compute_night_base_date_after_19h_is_today():
    now = datetime(2026, 7, 10, 20, 0, tzinfo=JST)
    assert warm.compute_night_base_date(now) == datetime(2026, 7, 10).date()


def test_compute_night_base_date_before_19h_rolls_back_a_day():
    now = datetime(2026, 7, 10, 18, 30, tzinfo=JST)
    assert warm.compute_night_base_date(now) == datetime(2026, 7, 9).date()


def test_is_night_completed_false_during_normal_operating_window():
    base_date = datetime(2026, 7, 10).date()
    now = datetime(2026, 7, 10, 20, 0, tzinfo=JST)
    assert warm.is_night_completed(base_date, now) is False


def test_is_night_completed_true_after_next_day_5am():
    base_date = datetime(2026, 7, 9).date()  # "yesterday" from now's perspective
    now = datetime(2026, 7, 10, 20, 0, tzinfo=JST)
    assert warm.is_night_completed(base_date, now) is True


def test_ymd_and_ymd_compact():
    d = datetime(2026, 7, 9).date()
    assert warm.ymd(d) == "2026-07-09"
    assert warm.ymd_compact(d) == "20260709"


def test_build_store_urls_matches_client_shapes_during_evening_window():
    now = datetime(2026, 7, 10, 20, 0, tzinfo=JST)
    stores = [{"slug": "nagasaki", "lat": 32.74, "lon": 129.88}]
    urls = warm.build_store_urls("https://example.test", stores, now)
    by_label = {u.label: u for u in urls}

    assert len(urls) == 4
    assert (
        by_label["nagasaki:range_today"].url
        == "https://example.test/api/range?store=nagasaki&from=2026-07-10&to=2026-07-11&limit=240"
    )
    assert by_label["nagasaki:range_today"].prefix == "range"
    assert (
        by_label["nagasaki:range_yesterday"].url
        == "https://example.test/api/range?store=nagasaki&from=2026-07-09&to=2026-07-10&limit=1200"
    )
    assert by_label["nagasaki:range_yesterday"].prefix == "range"
    # In-progress "today" night -> forecast_today (not the snapshot).
    assert by_label["nagasaki:forecast_today"].url == "https://example.test/api/forecast_today?store=nagasaki"
    assert by_label["nagasaki:forecast_today"].prefix == "forecast_today"
    # "yesterday" tab's night is always completed by the time this script runs.
    assert (
        by_label["nagasaki:forecast_yesterday_snapshot"].url
        == "https://example.test/api/forecast_snapshot?store=nagasaki&date=20260709"
    )
    assert by_label["nagasaki:forecast_yesterday_snapshot"].prefix == "forecast_snapshot"


def test_build_list_page_urls_splits_into_pages_of_12_in_file_order():
    stores = [{"slug": f"s{i}", "lat": 0.0, "lon": 0.0} for i in range(1, 15)]  # 14 stores
    urls = warm.build_list_page_urls("https://example.test", stores)

    # 2 pages (12 + 2) * 3 endpoints each.
    assert len(urls) == 6

    page1_csv = ",".join(f"s{i}" for i in range(1, 13))
    page2_csv = ",".join(["s13", "s14"])

    by_label = {u.label: u for u in urls}
    assert (
        by_label["list_page1:range_multi"].url
        == f"https://example.test/api/range_multi?stores={page1_csv}&limit=48"
    )
    assert by_label["list_page1:range_multi"].prefix == "range_multi"
    assert (
        by_label["list_page1:forecast_today_multi"].url
        == f"https://example.test/api/forecast_today_multi?stores={page1_csv}"
    )
    assert by_label["list_page1:forecast_today_multi"].prefix == "forecast_multi"
    assert by_label["list_page1:megribi_score"].url == f"https://example.test/api/megribi_score?stores={page1_csv}"
    assert by_label["list_page1:megribi_score"].prefix == "megribi_score"

    assert (
        by_label["list_page2:range_multi"].url
        == f"https://example.test/api/range_multi?stores={page2_csv}&limit=48"
    )


def test_build_top_page_urls_uses_bare_megribi_score_and_first_store_as_default():
    stores = [{"slug": "nagasaki", "lat": 0.0, "lon": 0.0}, {"slug": "fukuoka", "lat": 0.0, "lon": 0.0}]
    urls = warm.build_top_page_urls("https://example.test", stores)
    by_label = {u.label: u for u in urls}

    assert by_label["top:megribi_score"].url == "https://example.test/api/megribi_score"
    assert by_label["top:megribi_score"].prefix == "megribi_score"
    assert by_label["top:range_default_store"].url == "https://example.test/api/range?store=nagasaki&limit=48"
    assert by_label["top:range_default_store"].prefix == "range"


def test_haversine_km_matches_closed_form_for_one_degree_of_longitude_at_equator():
    # At the equator, 1 degree of longitude subtends an arc of R * radians(1).
    expected = 6371.0 * math.radians(1.0)
    got = warm.haversine_km(0.0, 0.0, 0.0, 1.0)
    assert got == pytest.approx(expected)


def test_haversine_km_zero_distance_to_self_and_symmetric():
    assert warm.haversine_km(35.6, 139.7, 35.6, 139.7) == 0.0
    a_to_b = warm.haversine_km(35.6, 139.7, 34.7, 135.5)
    b_to_a = warm.haversine_km(34.7, 135.5, 35.6, 139.7)
    assert a_to_b == pytest.approx(b_to_a)


def test_nearest_related_slugs_orders_by_distance_excludes_self_and_far_store():
    # Points on a meridian (same longitude) so distance is monotonic in |lat diff|.
    stores = [
        {"slug": "a", "lat": 0.0, "lon": 0.0},
        {"slug": "b", "lat": 1.0, "lon": 0.0},
        {"slug": "c", "lat": 2.0, "lon": 0.0},
        {"slug": "d", "lat": 3.0, "lon": 0.0},
        {"slug": "e", "lat": 4.0, "lon": 0.0},
        {"slug": "far", "lat": 10.0, "lon": 0.0},
    ]
    related = warm.nearest_related_slugs(stores, "a")
    assert related == ["b", "c", "d", "e"]  # nearest 4, "far" excluded, "a" excluded


def test_build_related_store_urls_one_per_store_with_own_nearest4_csv():
    stores = [
        {"slug": "a", "lat": 0.0, "lon": 0.0},
        {"slug": "b", "lat": 1.0, "lon": 0.0},
        {"slug": "c", "lat": 2.0, "lon": 0.0},
        {"slug": "d", "lat": 3.0, "lon": 0.0},
        {"slug": "e", "lat": 4.0, "lon": 0.0},
    ]
    urls = warm.build_related_store_urls("https://example.test", stores)
    assert len(urls) == len(stores)
    by_label = {u.label: u for u in urls}
    assert (
        by_label["a:related_range_multi"].url
        == "https://example.test/api/range_multi?stores=b,c,d,e&limit=48"
    )
    assert by_label["a:related_range_multi"].prefix == "range_multi"


def test_build_all_urls_interleaves_related_range_multi_instead_of_clustering():
    # Regression test for a real 429 burst hit in the first live verification
    # run: appending all "related stores" range_multi hits as one trailing
    # block clusters ~43 same-prefix requests together and trips the app's
    # own rate limiter. build_all_urls must interleave each store's related
    # hit right after that store's own block instead.
    now = datetime(2026, 7, 10, 20, 0, tzinfo=JST)
    stores = [
        {"slug": "a", "lat": 0.0, "lon": 0.0},
        {"slug": "b", "lat": 1.0, "lon": 0.0},
        {"slug": "c", "lat": 2.0, "lon": 0.0},
        {"slug": "d", "lat": 3.0, "lon": 0.0},
        {"slug": "e", "lat": 4.0, "lon": 0.0},
    ]
    urls = warm.build_all_urls("https://example.test", stores, now)
    labels = [u.label for u in urls]

    # top(2) + list_page(1 page * 3) + per-store(5 stores * 5: 4 own + 1 related) = 30
    assert len(labels) == 2 + 3 + 5 * 5

    a_block_start = labels.index("a:range_today")
    # Store "a"'s own 4 requests, immediately followed by its related hit --
    # NOT 43 (or here, 5) related hits bunched together at the end.
    assert labels[a_block_start : a_block_start + 5] == [
        "a:range_today",
        "a:range_yesterday",
        "a:forecast_today",
        "a:forecast_yesterday_snapshot",
        "a:related_range_multi",
    ]
    # The related hits must not all be adjacent at the tail of the list.
    related_indices = [i for i, label in enumerate(labels) if label.endswith(":related_range_multi")]
    assert related_indices != list(range(len(labels) - len(related_indices), len(labels)))


def test_parse_hhmm_to_minutes():
    assert warm.parse_hhmm_to_minutes("18:55") == 18 * 60 + 55
    assert warm.parse_hhmm_to_minutes("24:05") == 24 * 60 + 5
    assert warm.parse_hhmm_to_minutes("00:05") == 5


def test_in_warm_window_handles_midnight_wraparound():
    start, end = "18:55", "24:05"
    assert warm.in_warm_window(datetime(2026, 7, 10, 18, 55, tzinfo=JST), start, end) is True
    assert warm.in_warm_window(datetime(2026, 7, 10, 18, 54, tzinfo=JST), start, end) is False
    assert warm.in_warm_window(datetime(2026, 7, 10, 20, 0, tzinfo=JST), start, end) is True
    assert warm.in_warm_window(datetime(2026, 7, 11, 0, 3, tzinfo=JST), start, end) is True
    assert warm.in_warm_window(datetime(2026, 7, 11, 0, 10, tzinfo=JST), start, end) is False
    assert warm.in_warm_window(datetime(2026, 7, 10, 12, 0, tzinfo=JST), start, end) is False
