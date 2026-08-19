"""店舗マスタ（frontend/src/data/stores.json）読み込みの共有ヘルパー（stdlib のみ）。

CLAUDE.md §3 のとおり stores.json は店舗マスタの唯一の正本だが、scripts/ 配下では
5本のスクリプトがそれぞれ手書きで読み、さらに slug -> store_id の変換が
「stores.json 参照」と「`ay_` 接頭辞ヒューリスティック」の2流儀に分かれていた。
ここに「読み込み」と「変換規約」を集約する。

**エラー時のポリシーは意図的にここへ持ち込まない。** stores.json が無い/壊れている
ときに「ジョブを落とす」のか「警告して続ける」のかはスクリプトごとに異なる仕様
（日次レポート・patch は落とす／週報は落とさない）なので、`load_stores_json` は
例外をそのまま送出し、判断は呼び出し元のラッパーに残す。

scripts/_supabase_common.py と同じ規約で、呼び出し側が
`sys.path.insert(0, <自分のディレクトリ>)` した上でベアインポートする。
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
STORES_JSON_PATH = REPO_ROOT / "frontend" / "src" / "data" / "stores.json"


def load_stores_json(path: Path | None = None) -> list[dict]:
    """stores.json を読んで行(dict)のリストをファイル順のまま返す。

    ファイルが無い/壊れている場合は例外（OSError / json.JSONDecodeError）をそのまま
    送出する ― どう扱うかは呼び出し元の仕様。
    """
    return json.loads((path or STORES_JSON_PATH).read_text(encoding="utf-8"))


def all_slugs(path: Path | None = None) -> list[str]:
    """全店舗の slug をファイル順で返す（`--stores all` 等の展開用）。"""
    return [row["slug"] for row in load_stores_json(path) if row.get("slug")]


def slug_to_store_id_map(path: Path | None = None) -> dict[str, str]:
    """slug -> store_id の対応表。"""
    rows = load_stores_json(path)
    return {r["slug"]: r["store_id"] for r in rows if r.get("slug") and r.get("store_id")}


_STORE_ID_CACHE: dict[str, str] | None = None


def slug_to_store_id(slug: str) -> str:
    """フロント slug -> serving store_id。**stores.json の store_id が正**。

    stores.json に無い slug、または stores.json 自体が読めない場合のみ、旧来の
    ヒューリスティック（`ay_` で始まればそのまま、それ以外は `ol_` を付与）へ
    フォールバックする（バッチを落とさないため）。現行42店では両者は全件一致する
    ＝この関数への移行は挙動不変。tests/test_stores_common.py で固定。

    1プロセス内で1回だけ読み込みキャッシュする。
    """
    global _STORE_ID_CACHE
    if _STORE_ID_CACHE is None:
        try:
            _STORE_ID_CACHE = slug_to_store_id_map()
        except Exception:  # noqa: BLE001 - 読めなければヒューリスティックで継続
            _STORE_ID_CACHE = {}
    store_id = _STORE_ID_CACHE.get(slug)
    if store_id:
        return store_id
    return slug if slug.startswith("ay_") else f"ol_{slug}"
