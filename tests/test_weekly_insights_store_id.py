"""_store_id_for_slug (scripts/generate_weekly_insights.py) の store_id 解決テスト。

回帰対象のバグ: _upsert_weekly_report_to_supabase が全店舗に `f"ol_{store}"` を
ハードコードしていたため、相席屋の slug (store_id が `ay_*`) で不正な store_id
(例: `ol_ay_niigata` のような形にはならないが、実際には `_ag` サフィックス付き
oriental AG サブブランドと混同されるケースや、将来 aisekiya slug が矩阵に
追加された場合に `ol_ay_niigata` 等の不正値が書き込まれるケース) が発生していた。

stores.json (PR #28 で単一ソース化) を正とし、slug -> store_id を解決する。
"""

from __future__ import annotations

import json

import pytest

from scripts.generate_weekly_insights import (
    STORES_JSON_PATH,
    _load_slug_to_store_id_map,
    _store_id_for_slug,
)


def _real_mapping() -> dict[str, str]:
    data = json.loads(STORES_JSON_PATH.read_text(encoding="utf-8"))
    return {row["slug"]: row["store_id"] for row in data if row.get("slug") and row.get("store_id")}


class TestStoreIdForSlugAgainstRealStoresJson:
    """実際の stores.json (frontend/src/data/stores.json) を対象にした検証。"""

    def test_aisekiya_slug_maps_to_ay_store_id(self) -> None:
        # 相席屋 (brand=aisekiya) の slug は ay_ プレフィックスで、store_id もそのまま ay_*。
        mapping = _real_mapping()
        aisekiya_slugs = [
            slug for slug, sid in mapping.items() if sid.startswith("ay_")
        ]
        assert aisekiya_slugs, "no aisekiya (ay_*) entries found in stores.json"
        sample_slug = aisekiya_slugs[0]
        resolved = _store_id_for_slug(sample_slug)
        assert resolved == mapping[sample_slug]
        assert resolved.startswith("ay_")

    def test_oriental_slug_maps_to_ol_store_id(self) -> None:
        resolved = _store_id_for_slug("shibuya")
        assert resolved == "ol_shibuya"

    def test_oriental_ag_subbrand_slug_maps_to_ol_store_id(self) -> None:
        # `_ag` サフィックスは oriental の AG サブブランドであり、相席屋ではない。
        # store_id は ol_ プレフィックスのまま (ay_ に化けない) ことを確認する。
        resolved = _store_id_for_slug("shibuya_ag")
        assert resolved == "ol_shibuya_ag"

    def test_unknown_slug_falls_back_with_warning(self, capsys: pytest.CaptureFixture[str]) -> None:
        resolved = _store_id_for_slug("this_slug_does_not_exist_anywhere")
        assert resolved == "ol_this_slug_does_not_exist_anywhere"
        captured = capsys.readouterr()
        assert "WARNING" in captured.err
        assert "this_slug_does_not_exist_anywhere" in captured.err


class TestLoadSlugToStoreIdMapCaching:
    def test_returns_same_dict_object_on_repeated_calls(self) -> None:
        first = _load_slug_to_store_id_map()
        second = _load_slug_to_store_id_map()
        assert first is second  # cached, not reloaded


class TestStoreIdForSlugWithMissingStoresJson:
    """stores.json が読めない場合でもジョブを落とさず ol_ フォールバックすること。"""

    def test_missing_file_falls_back_without_crash(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        import scripts.generate_weekly_insights as mod

        monkeypatch.setattr(mod, "_SLUG_TO_STORE_ID_CACHE", None)
        monkeypatch.setattr(mod, "STORES_JSON_PATH", mod.REPO_ROOT / "does" / "not" / "exist.json")

        resolved = mod._store_id_for_slug("shibuya")

        assert resolved == "ol_shibuya"
        captured = capsys.readouterr()
        assert "stores.json not found" in captured.err

        # テスト後にキャッシュを元へ戻す（他テストへの汚染防止）
        monkeypatch.setattr(mod, "_SLUG_TO_STORE_ID_CACHE", None)
