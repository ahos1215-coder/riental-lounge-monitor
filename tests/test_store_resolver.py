from oriental.utils.stores import (
    AISEKIYA_STORE_IDS,
    ALL_STORE_IDS,
    SLUG_TO_ID,
    resolve_store_identifier,
    resolve_store_identifier_strict,
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


# ---------- resolve_store_identifier_strict（bug #5: /api/range 用の厳格版） ----------


def test_strict_resolves_every_known_store():
    for sid in ALL_STORE_IDS:
        resolved = resolve_store_identifier_strict(sid)
        assert resolved is not None
        assert resolved[0] == sid


def test_strict_resolves_short_slugs():
    for sid in [s for s in ALL_STORE_IDS if s.startswith("ol_")]:
        short_slug = sid.split("ol_", 1)[-1]
        resolved = resolve_store_identifier_strict(short_slug)
        assert resolved is not None
        assert resolved[0] == sid


def test_strict_returns_none_for_unknown_slug():
    assert resolve_store_identifier_strict("nagoya") is None
    assert resolve_store_identifier_strict("totally_unknown_store") is None


def test_strict_returns_none_for_closed_store_sapporo_ag():
    # sapporo_ag は 2026-07-11 閉店で stores.json から削除済み。
    assert resolve_store_identifier_strict("sapporo_ag") is None
    assert resolve_store_identifier_strict("ol_sapporo_ag") is None


def test_strict_returns_none_for_empty_or_missing():
    assert resolve_store_identifier_strict(None) is None
    assert resolve_store_identifier_strict("") is None
    assert resolve_store_identifier_strict("   ") is None


def test_lenient_and_strict_agree_on_all_known_stores():
    """resolve_store_identifier（寛容版）は resolve_store_identifier_strict に委譲しているため、
    既知store全てで両者が同じ結果を返す（byte-identical であることの回帰ガード）。"""
    for sid in ALL_STORE_IDS:
        lenient = resolve_store_identifier(sid, "ol_should_not_be_used")
        strict = resolve_store_identifier_strict(sid)
        assert lenient == strict
