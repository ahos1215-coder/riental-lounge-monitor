from oriental.utils.stores import (
    AISEKIYA_STORE_IDS,
    SLUG_TO_ID,
    resolve_store_identifier,
)


def test_resolve_slug_to_store_id():
    sid, slug = resolve_store_identifier("nagasaki", "ol_default")
    assert sid == "ol_nagasaki"
    assert slug == "nagasaki"


def test_resolve_aisekiya_store_id_is_not_defaulted():
    # 相席屋の slug は store_id とそのまま同じ ("ay_ueno")。以前は STORE_IDS/SLUG_TO_ID
    # に無く default (ol_nagasaki) に落ちて別店舗のデータを返していた回帰を防ぐ。
    for sid_expected in AISEKIYA_STORE_IDS:
        sid, slug = resolve_store_identifier(sid_expected, "ol_nagasaki")
        assert sid == sid_expected, f"{sid_expected} resolved to {sid} (should be self, not default)"
        assert slug == sid_expected


def test_aisekiya_slugs_in_slug_to_id():
    # range_multi / forecast_multi は SLUG_TO_ID を参照するため、相席屋 slug が含まれること。
    for sid in AISEKIYA_STORE_IDS:
        assert SLUG_TO_ID.get(sid) == sid


def test_resolve_store_id_passthrough():
    sid, slug = resolve_store_identifier("ol_fukuoka", "ol_default")
    assert sid == "ol_fukuoka"
    assert slug == "fukuoka"


def test_resolve_unknown_fallbacks_to_default():
    sid, slug = resolve_store_identifier("unknown", "ol_default")
    assert sid == "ol_default"
    assert slug == "default"
