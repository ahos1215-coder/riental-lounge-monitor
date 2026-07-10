"""store_id 一覧(STORE_IDS/AISEKIYA_STORE_IDS)の単一ソース(SSOT)整合性テスト。

oriental/utils/stores.py は本来 frontend/src/data/stores.json を単一ソースとして
STORE_IDS / AISEKIYA_STORE_IDS を導出するが、stores.json が読めない場合に備えて
_FALLBACK_STORE_IDS / _FALLBACK_AISEKIYA_STORE_IDS というハードコードされた安全網も
持っている。

このテストは:
  1. 通常経路（stores.json が読める）では、導出結果とフォールバックが完全一致すること
     を検証する。もし新しい店舗が stores.json に追加されたのにフォールバックが
     更新されていなければ、このテストが「順序込みで不一致」として大きな音で
     知らせる（どちらを直すべきかもメッセージに明記する）。
  2. stores.json の store_id 集合が SLUG_TO_ID のカバレッジと一致していること。
  3. resolve_store_identifier が全店舗を正しく解決し、未知の入力は default にのみ
     フォールバックすること。
"""

from __future__ import annotations

import json
from pathlib import Path

from oriental.utils.stores import (
    _FALLBACK_AISEKIYA_STORE_IDS,
    _FALLBACK_STORE_IDS,
    ALL_STORE_IDS,
    AISEKIYA_STORE_IDS,
    SLUG_TO_ID,
    STORE_IDS,
    resolve_store_identifier,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
STORES_JSON = REPO_ROOT / "frontend" / "src" / "data" / "stores.json"


def _stores_json_rows() -> list[dict]:
    return json.loads(STORES_JSON.read_text(encoding="utf-8"))


def test_store_ids_match_fallback_exactly():
    assert STORE_IDS == _FALLBACK_STORE_IDS, (
        "stores.json から導出した oriental STORE_IDS が "
        "oriental/utils/stores.py の _FALLBACK_STORE_IDS と一致しません(順序含む)。\n"
        "stores.json に店舗を追加/変更した場合は _FALLBACK_STORE_IDS を stores.json の "
        "並び順に合わせて更新してください(逆に stores.json 側のミスなら stores.json を直してください)。\n"
        f"derived={STORE_IDS}\nfallback={_FALLBACK_STORE_IDS}"
    )


def test_aisekiya_store_ids_match_fallback_exactly():
    assert AISEKIYA_STORE_IDS == _FALLBACK_AISEKIYA_STORE_IDS, (
        "stores.json から導出した aisekiya AISEKIYA_STORE_IDS が "
        "oriental/utils/stores.py の _FALLBACK_AISEKIYA_STORE_IDS と一致しません(順序含む)。\n"
        "stores.json に店舗を追加/変更した場合は _FALLBACK_AISEKIYA_STORE_IDS を stores.json の "
        "並び順に合わせて更新してください(逆に stores.json 側のミスなら stores.json を直してください)。\n"
        f"derived={AISEKIYA_STORE_IDS}\nfallback={_FALLBACK_AISEKIYA_STORE_IDS}"
    )


def test_stores_json_store_id_set_matches_slug_to_id_coverage():
    rows = _stores_json_rows()
    json_store_ids = {r["store_id"] for r in rows if r.get("store_id")}
    slug_to_id_targets = set(SLUG_TO_ID.values())
    assert json_store_ids == slug_to_id_targets, (
        f"stores.json の store_id 集合と SLUG_TO_ID のカバレッジが不一致です。\n"
        f"stores.json のみ={json_store_ids - slug_to_id_targets}\n"
        f"SLUG_TO_ID のみ={slug_to_id_targets - json_store_ids}"
    )
    # ALL_STORE_IDS も同じ集合を指しているはず
    assert set(ALL_STORE_IDS) == json_store_ids


def test_resolve_store_identifier_resolves_every_store():
    for sid in ALL_STORE_IDS:
        resolved_sid, _slug = resolve_store_identifier(sid, "ol_default_should_not_be_used")
        assert resolved_sid == sid, f"store_id {sid} did not resolve to itself"

    # オリエンタルは "ol_" を剥がした短縮 slug でも解決できる
    for sid in STORE_IDS:
        short_slug = sid.split("ol_", 1)[-1]
        resolved_sid, _slug = resolve_store_identifier(short_slug, "ol_default_should_not_be_used")
        assert resolved_sid == sid, f"slug {short_slug} did not resolve to {sid}"


def test_resolve_store_identifier_falls_back_for_unknown():
    sid, slug = resolve_store_identifier("totally_unknown_store", "ol_kobe")
    assert sid == "ol_kobe"
    assert slug == "kobe"
