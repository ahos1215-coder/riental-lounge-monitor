"""相席屋の座席数(capacity)の単一ソース(SSOT)整合性テスト。

capacity の出典は 3 箇所に分かれて存在する:
  1. frontend/src/data/stores.json の各店 `capacity`（= 片性別の座席数。フロント
     `config/stores.ts` と バックエンド `oriental/utils/stores.py` が読む単一ソース）
  2. multi_collect.py の AISEKIYA_STORES（生の座席レイアウト tables/vip。
     `_aisekiya_capacity()` が (tables+vip)*2 = 片性別座席数 を返す）
  3. oriental/utils/stores.py の AISEKIYA_TOTAL_CAPACITY（= stores.json.capacity*2 を導出）

このテストは 1↔2↔3 が一致していることを保証し、店舗レイアウト変更時の
「片方だけ更新して片方が古いまま」というドリフトを CI で検知する。
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
STORES_JSON = REPO_ROOT / "frontend" / "src" / "data" / "stores.json"


def _stores_json_capacities() -> dict[str, int]:
    rows = json.loads(STORES_JSON.read_text(encoding="utf-8"))
    return {
        r["store_id"]: r["capacity"]
        for r in rows
        if r.get("brand") == "aisekiya" and isinstance(r.get("capacity"), (int, float))
    }


def test_every_aisekiya_store_has_capacity_in_stores_json():
    rows = json.loads(STORES_JSON.read_text(encoding="utf-8"))
    aisekiya = [r for r in rows if r.get("brand") == "aisekiya"]
    assert aisekiya, "no aisekiya stores found in stores.json"
    missing = [r["store_id"] for r in aisekiya if not isinstance(r.get("capacity"), (int, float))]
    assert not missing, f"aisekiya stores missing numeric capacity: {missing}"


def test_oriental_stores_have_no_capacity_field():
    rows = json.loads(STORES_JSON.read_text(encoding="utf-8"))
    leaked = [r["store_id"] for r in rows if r.get("brand") != "aisekiya" and "capacity" in r]
    assert not leaked, f"non-aisekiya stores unexpectedly carry capacity: {leaked}"


def test_stores_json_capacity_matches_multi_collect_layout():
    """stores.json.capacity == multi_collect の (tables+vip)*2（生レイアウトからの計算値）。"""
    import multi_collect

    caps = _stores_json_capacities()
    checked = 0
    for slug, info in multi_collect.AISEKIYA_STORES.items():
        store_id = info["store_id"]
        raw_cap = multi_collect._aisekiya_capacity(slug)  # (tables + vip) * 2
        assert store_id in caps, f"{store_id} present in multi_collect but missing capacity in stores.json"
        assert caps[store_id] == raw_cap, (
            f"capacity drift for {store_id}: stores.json={caps[store_id]} "
            f"vs multi_collect (tables+vip)*2={raw_cap}"
        )
        checked += 1
    assert checked == len(caps), (
        f"store-count mismatch: multi_collect has {checked} aisekiya stores, "
        f"stores.json has {len(caps)}"
    )


def test_backend_total_capacity_is_derived_from_stores_json():
    """oriental/utils/stores.py の AISEKIYA_TOTAL_CAPACITY == stores.json.capacity * 2。"""
    from oriental.utils.stores import AISEKIYA_TOTAL_CAPACITY

    caps = _stores_json_capacities()
    assert caps, "no aisekiya capacities loaded from stores.json"
    for store_id, per_gender in caps.items():
        assert store_id in AISEKIYA_TOTAL_CAPACITY, f"{store_id} missing from AISEKIYA_TOTAL_CAPACITY"
        assert AISEKIYA_TOTAL_CAPACITY[store_id] == int(per_gender) * 2, (
            f"total-capacity mismatch for {store_id}: "
            f"backend={AISEKIYA_TOTAL_CAPACITY[store_id]} vs stores.json*2={int(per_gender) * 2}"
        )
