from oriental.utils.stores import resolve_store_identifier


def test_resolve_slug_to_store_id():
    sid, slug = resolve_store_identifier("nagasaki", "ol_default")
    assert sid == "ol_nagasaki"
    assert slug == "nagasaki"


def test_resolve_store_id_passthrough():
    sid, slug = resolve_store_identifier("ol_fukuoka", "ol_default")
    assert sid == "ol_fukuoka"
    assert slug == "fukuoka"


def test_resolve_unknown_fallbacks_to_default():
    sid, slug = resolve_store_identifier("unknown", "ol_default")
    assert sid == "ol_default"
    assert slug == "default"
