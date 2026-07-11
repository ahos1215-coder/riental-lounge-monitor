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

    # 2 pages (12 + 2) * 2 endpoints each (megribi_score removed -- see
    # test_build_list_page_urls_does_not_warm_megribi_score below).
    assert len(urls) == 4

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

    assert (
        by_label["list_page2:range_multi"].url
        == f"https://example.test/api/range_multi?stores={page2_csv}&limit=48"
    )


def test_build_list_page_urls_does_not_warm_megribi_score():
    # Regression test for bug audit rank7: the judgment UI that consumes
    # megribi_score is behind SHOW_MEGRIBI_JUDGMENTS (currently false), so
    # warming it is wasted backend load. See featureFlags.ts.
    stores = [{"slug": f"s{i}", "lat": 0.0, "lon": 0.0} for i in range(1, 15)]
    urls = warm.build_list_page_urls("https://example.test", stores)
    assert all("megribi_score" not in u.label and "megribi_score" not in u.prefix for u in urls)
    assert all("megribi_score" not in u.url for u in urls)


# --------------------------------------------------------------------------
# Brand-tab / region-filter coverage (2026-07-11 filter-combo coverage --
# see the module docstring in warm_cdn_local.py for the full rationale).
# --------------------------------------------------------------------------


def test_normalize_brand_matches_frontend_default_mapping():
    # Mirrors config/stores.ts: only "aisekiya"/"jis" are preserved, anything
    # else (including None/missing) normalizes to "oriental".
    assert warm.normalize_brand("aisekiya") == "aisekiya"
    assert warm.normalize_brand("jis") == "jis"
    assert warm.normalize_brand("oriental") == "oriental"
    assert warm.normalize_brand(None) == "oriental"
    assert warm.normalize_brand("") == "oriental"
    assert warm.normalize_brand("something-unexpected") == "oriental"


def test_load_stores_includes_brand_and_region_label_from_real_stores_json():
    # 42 stores as of the 2026-07-11 sapporo_ag closure (CLAUDE.md ss1):
    # 37 oriental + 5 aisekiya, no "jis" entries yet.
    stores = warm.load_stores()
    assert len(stores) == 42
    brands = [s["brand"] for s in stores]
    assert brands.count("oriental") == 37
    assert brands.count("aisekiya") == 5
    assert brands.count("jis") == 0
    assert all(s["region_label"] for s in stores)


def test_brand_filter_groups_preserves_stores_json_order_and_skips_zero_count_brands():
    stores = [
        {"slug": "a", "brand": "oriental", "region_label": "kanto"},
        {"slug": "b", "brand": "aisekiya", "region_label": "kanto"},
        {"slug": "c", "brand": "oriental", "region_label": "kansai"},
    ]
    groups = warm.brand_filter_groups(stores)
    # First-occurrence order: "oriental" (store a) before "aisekiya" (store b).
    assert [b for b, _ in groups] == ["oriental", "aisekiya"]
    by_brand = dict(groups)
    assert [s["slug"] for s in by_brand["oriental"]] == ["a", "c"]  # order preserved
    assert [s["slug"] for s in by_brand["aisekiya"]] == ["b"]
    assert "jis" not in by_brand  # zero stores -> absent, not an empty list


def test_region_filter_groups_preserves_stores_json_order():
    stores = [
        {"slug": "a", "brand": "oriental", "region_label": "kanto"},
        {"slug": "b", "brand": "oriental", "region_label": "kansai"},
        {"slug": "c", "brand": "aisekiya", "region_label": "kanto"},
    ]
    groups = warm.region_filter_groups(stores)
    assert [r for r, _ in groups] == ["kanto", "kansai"]
    by_region = dict(groups)
    assert [s["slug"] for s in by_region["kanto"]] == ["a", "c"]
    assert [s["slug"] for s in by_region["kansai"]] == ["b"]


def test_build_paged_multi_urls_empty_group_yields_no_urls():
    assert warm.build_paged_multi_urls("https://example.test", [], "brand_jis") == []


def test_build_filter_page_urls_brand_examples_match_real_stores_json():
    # Literal known-good example built from the current 42-store roster
    # (independently re-filtered here, not via warm.brand_filter_groups).
    stores = warm.load_stores()
    oriental_slugs = [s["slug"] for s in stores if s["brand"] == "oriental"]
    aisekiya_slugs = [s["slug"] for s in stores if s["brand"] == "aisekiya"]
    assert len(oriental_slugs) == 37  # -> ceil(37/12) = 4 pages
    assert len(aisekiya_slugs) == 5  # -> 1 page

    urls = warm.build_filter_page_urls("https://example.test", stores)
    by_label = {u.label: u for u in urls}

    page1_csv = ",".join(oriental_slugs[0:12])
    page4_csv = ",".join(oriental_slugs[36:37])  # last, partial page (1 store)
    assert (
        by_label["brand_oriental_page1:range_multi"].url
        == f"https://example.test/api/range_multi?stores={page1_csv}&limit=48"
    )
    assert by_label["brand_oriental_page1:range_multi"].prefix == "range_multi"
    assert (
        by_label["brand_oriental_page1:forecast_today_multi"].url
        == f"https://example.test/api/forecast_today_multi?stores={page1_csv}"
    )
    assert by_label["brand_oriental_page1:forecast_today_multi"].prefix == "forecast_multi"
    assert (
        by_label["brand_oriental_page4:range_multi"].url
        == f"https://example.test/api/range_multi?stores={page4_csv}&limit=48"
    )
    assert "brand_oriental_page5:range_multi" not in by_label  # exactly 4 pages, no more

    aisekiya_csv = ",".join(aisekiya_slugs)
    assert (
        by_label["brand_aisekiya_page1:range_multi"].url
        == f"https://example.test/api/range_multi?stores={aisekiya_csv}&limit=48"
    )
    assert "brand_aisekiya_page2:range_multi" not in by_label  # 5 stores fit on 1 page


def test_build_filter_page_urls_region_examples_match_real_stores_json():
    # Literal known-good example for the region filter: 海外 (overseas) is a
    # single-store region today (gangnam, Seoul) -- exactly 1 page, no page 2.
    stores = warm.load_stores()
    overseas_slugs = [s["slug"] for s in stores if s["region_label"] == "海外"]
    assert overseas_slugs == ["gangnam"]

    urls = warm.build_filter_page_urls("https://example.test", stores)
    by_label = {u.label: u for u in urls}

    assert (
        by_label["region_海外_page1:range_multi"].url
        == "https://example.test/api/range_multi?stores=gangnam&limit=48"
    )
    assert by_label["region_海外_page1:range_multi"].prefix == "range_multi"
    assert (
        by_label["region_海外_page1:forecast_today_multi"].url
        == "https://example.test/api/forecast_today_multi?stores=gangnam"
    )
    assert "region_海外_page2:range_multi" not in by_label


def test_build_filter_page_urls_excludes_default_view_and_zero_count_jis_tab():
    stores = warm.load_stores()
    urls = warm.build_filter_page_urls("https://example.test", stores)
    labels = [u.label for u in urls]
    # "すべて" (all) IS the default view, already covered by build_list_page_urls
    # -- build_filter_page_urls must not duplicate it under any label.
    assert not any(label.startswith("brand_all") for label in labels)
    # "jis" has zero stores.json entries (not yet scraped) -> zero fetches
    # client-side -> nothing to warm.
    assert not any(label.startswith("brand_jis") for label in labels)


def test_build_filter_page_urls_only_kanto_region_needs_a_second_page():
    # Derived dynamically from stores.json, not a hardcoded region list:
    # exactly the regions with > STORES_PER_PAGE stores should get a page 2.
    stores = warm.load_stores()
    region_counts = {r: len(g) for r, g in warm.region_filter_groups(stores)}
    expected_two_page_regions = {r for r, n in region_counts.items() if n > warm.STORES_PER_PAGE}
    assert expected_two_page_regions == {"関東"}  # 17 stores today

    urls = warm.build_filter_page_urls("https://example.test", stores)
    labels = {u.label for u in urls}
    for region in region_counts:
        assert f"region_{region}_page1:range_multi" in labels
        has_page2 = f"region_{region}_page2:range_multi" in labels
        assert has_page2 == (region in expected_two_page_regions)


def test_build_filter_page_urls_does_not_warm_megribi_score():
    stores = warm.load_stores()
    urls = warm.build_filter_page_urls("https://example.test", stores)
    assert all("megribi_score" not in u.label and "megribi_score" not in u.prefix for u in urls)


def test_build_all_urls_interleaves_filter_units_across_the_store_loop():
    # Small deterministic fixture: 4 stores, 2 brands x 2 regions -> exactly
    # 4 filter-page-pairs (1 page each, all groups <= STORES_PER_PAGE), which
    # evenly distributes to exactly 1 filter unit inserted right after each
    # store's own block+related hit (4 units / 4 stores).
    now = datetime(2026, 7, 10, 20, 0, tzinfo=JST)
    stores = [
        {"slug": "a", "lat": 0.0, "lon": 0.0, "brand": "oriental", "region_label": "kanto"},
        {"slug": "b", "lat": 1.0, "lon": 0.0, "brand": "oriental", "region_label": "kansai"},
        {"slug": "c", "lat": 2.0, "lon": 0.0, "brand": "aisekiya", "region_label": "kanto"},
        {"slug": "d", "lat": 3.0, "lon": 0.0, "brand": "aisekiya", "region_label": "kansai"},
    ]
    urls = warm.build_all_urls("https://example.test", stores, now)
    labels = [u.label for u in urls]

    # top(1) + list_page(1 page * 2) + 4 stores * (4 own + 1 related + 2 filter-pair) = 31
    assert len(labels) == 1 + 2 + 4 * 7

    assert labels == [
        "top:range_default_store",
        "list_page1:range_multi",
        "list_page1:forecast_today_multi",
        "a:range_today",
        "a:range_yesterday",
        "a:forecast_today",
        "a:forecast_yesterday_snapshot",
        "a:related_range_multi",
        "brand_oriental_page1:range_multi",
        "brand_oriental_page1:forecast_today_multi",
        "b:range_today",
        "b:range_yesterday",
        "b:forecast_today",
        "b:forecast_yesterday_snapshot",
        "b:related_range_multi",
        "brand_aisekiya_page1:range_multi",
        "brand_aisekiya_page1:forecast_today_multi",
        "c:range_today",
        "c:range_yesterday",
        "c:forecast_today",
        "c:forecast_yesterday_snapshot",
        "c:related_range_multi",
        "region_kanto_page1:range_multi",
        "region_kanto_page1:forecast_today_multi",
        "d:range_today",
        "d:range_yesterday",
        "d:forecast_today",
        "d:forecast_yesterday_snapshot",
        "d:related_range_multi",
        "region_kansai_page1:range_multi",
        "region_kansai_page1:forecast_today_multi",
    ]
    # A (range_multi, forecast_today_multi) pair always stays adjacent --
    # never split across an interleaving boundary.
    for i, label in enumerate(labels):
        if label.endswith(":range_multi") and (
            label.startswith("brand_") or label.startswith("region_") or label.startswith("list_")
        ):
            assert labels[i + 1] == label.replace(":range_multi", ":forecast_today_multi")


def test_build_all_urls_total_count_matches_default_plus_filter_urls_on_real_stores_json():
    now = datetime(2026, 7, 11, 20, 0, tzinfo=JST)
    stores = warm.load_stores()
    default_total = len(warm.build_all_urls("https://example.test", [dict(s, brand=None, region_label=None) for s in stores], now))
    full_total = len(warm.build_all_urls("https://example.test", stores, now))
    filter_only_total = len(warm.build_filter_page_urls("https://example.test", stores))
    assert filter_only_total == 26  # 5 brand pages + 8 region pages, x2 URLs/page
    assert full_total == default_total + filter_only_total
    assert full_total == 245  # 219 (pre-existing baseline) + 26


def test_build_all_urls_does_not_cluster_filter_units_densely(monkeypatch):
    # Regression guard for the same class of 429 burst that motivated the
    # related-stores interleaving: no long unbroken run of the same prefix.
    now = datetime(2026, 7, 11, 20, 0, tzinfo=JST)
    stores = warm.load_stores()
    urls = warm.build_all_urls("https://example.test", stores, now)

    max_run = 1
    run = 1
    for prev, cur in zip(urls, urls[1:]):
        if cur.prefix == prev.prefix:
            run += 1
            max_run = max(max_run, run)
        else:
            run = 1
    assert max_run <= 2  # e.g. a filter unit's range_multi landing right after
    # a related-stores range_multi hit -- never a long contiguous block.


def test_build_top_page_urls_uses_first_store_as_default_and_no_megribi_score():
    stores = [{"slug": "nagasaki", "lat": 0.0, "lon": 0.0}, {"slug": "fukuoka", "lat": 0.0, "lon": 0.0}]
    urls = warm.build_top_page_urls("https://example.test", stores)
    by_label = {u.label: u for u in urls}

    # Regression test for bug audit rank7: bare megribi_score removed (only
    # fed the now-hidden "今夜のおすすめ TOP5" panel).
    assert "top:megribi_score" not in by_label
    assert len(urls) == 1
    assert by_label["top:range_default_store"].url == "https://example.test/api/range?store=nagasaki&limit=48"
    assert by_label["top:range_default_store"].prefix == "range"


def test_build_top_page_urls_empty_stores_yields_no_urls():
    assert warm.build_top_page_urls("https://example.test", []) == []


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

    # top(1: megribi_score removed, rank7) + list_page(1 page * 2: megribi_score
    # removed) + per-store(5 stores * 5: 4 own + 1 related) = 28
    assert len(labels) == 1 + 2 + 5 * 5
    assert all("megribi_score" not in label for label in labels)

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


# --------------------------------------------------------------------------
# 429 mitigation (bug audit rank5) — pacing constants + fetch_with_backoff
# --------------------------------------------------------------------------


def test_pacing_constants_raised_for_429_mitigation():
    # 2026-07-11: base sleep raised 0.2 -> 0.3s, plus two new pacing layers.
    # Locks in the values referenced by plan/CDN_WARMING_LOCAL.md so the doc
    # and code can't silently drift apart.
    assert warm.DEFAULT_SLEEP_SECONDS == pytest.approx(0.3)
    assert warm.EXTRA_SLEEP_EVERY_N_REQUESTS == 20
    assert warm.DEFAULT_EXTRA_SLEEP_SECONDS == pytest.approx(1.0)
    assert warm.DEFAULT_BACKOFF_SECONDS == pytest.approx(2.5)


def test_fetch_with_backoff_passes_through_non_429_without_sleeping(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(warm, "fetch_one", lambda url, timeout=20: (True, 200, "HIT"))

    success, status, extra, hit_429 = warm.fetch_with_backoff(
        "https://example.test/x", sleep_fn=sleeps.append
    )

    assert (success, status, extra, hit_429) == (True, 200, "HIT", False)
    assert sleeps == []  # no backoff sleep for a clean 200


def test_fetch_with_backoff_backs_off_and_retries_once_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def fake_fetch_one(url, timeout=20):
        calls["n"] += 1
        if calls["n"] == 1:
            return False, 429, ""
        return True, 200, "MISS"

    monkeypatch.setattr(warm, "fetch_one", fake_fetch_one)
    sleeps: list[float] = []

    success, status, extra, hit_429 = warm.fetch_with_backoff(
        "https://example.test/x", backoff_seconds=2.5, sleep_fn=sleeps.append
    )

    assert calls["n"] == 2  # exactly one retry, not a loop
    assert sleeps == [2.5]  # backed off before the retry
    assert (success, status, extra, hit_429) == (True, 200, "MISS", True)


def test_fetch_with_backoff_still_429_after_retry_reports_failure_and_hit_429(monkeypatch):
    monkeypatch.setattr(warm, "fetch_one", lambda url, timeout=20: (False, 429, ""))
    sleeps: list[float] = []

    success, status, extra, hit_429 = warm.fetch_with_backoff(
        "https://example.test/x", backoff_seconds=2.5, sleep_fn=sleeps.append
    )

    # Still exactly one retry attempt (bounded worst case), not repeated backoff.
    assert sleeps == [2.5]
    assert (success, status, hit_429) == (False, 429, True)
