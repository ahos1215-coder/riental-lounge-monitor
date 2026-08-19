from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Tuple

# 全ブランドの store_id / capacity / lat・lon の単一ソース。oriental/ 内でこのファイルを
# 読むのは下の load_stores_rows() だけ（読み手が増えると新店追加時の見落としが増えるため）。
STORES_JSON_PATH = Path(__file__).resolve().parents[2] / "frontend" / "src" / "data" / "stores.json"


def load_stores_rows() -> list[dict]:
    """stores.json を list[dict] として返す。読めない/壊れている場合は [] を返す。

    呼び出し側が素朴に `row.get(...)` できるよう、list でない JSON や dict 以外の要素は
    ここで落とす（本関数は絶対に raise しない = 起動やリクエストを巻き添えにしない）。
    """
    try:
        rows = json.loads(STORES_JSON_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(rows, list):
        return []
    return [r for r in rows if isinstance(r, dict)]


# --- フォールバック専用（private） ---------------------------------------
# 単一ソースは frontend/src/data/stores.json。STORE_IDS / AISEKIYA_STORE_IDS は
# 本来これらを直接書かずに stores.json から導出する（下の
# _load_store_ids_from_stores_json を参照）。ここに残すハードコードは
# stores.json が読めない/壊れている場合の安全網としてのみ使う
# （Render は stores.json が万一欠けても起動できなければならない）。
#
# Known Supabase store_ids (37 stores; ol_sapporo_ag 除外 2026-07-11 閉店)。
# Kept minimal (id/slug) to avoid duplicating store metadata.
_FALLBACK_STORE_IDS = [
    "ol_nagasaki",
    "ol_fukuoka",
    "ol_kokura",
    "ol_oita",
    "ol_kumamoto",
    "ol_miyazaki",
    "ol_kagoshima",
    "ol_okinawa_ag",
    "ol_gangnam",
    "ol_sendai_ag",
    "ol_shibuya",
    "ol_ebisu",
    "ol_shibuya_ag",
    "ol_shinjuku",
    "ol_ueno",
    "ol_ueno_ag",
    "ol_kashiwa",
    "ol_machida",
    "ol_yokohama",
    "ol_omiya",
    "ol_utsunomiya",
    "ol_takasaki",
    "ol_nagoya_ag",
    "ol_nagoya_nishiki",
    "ol_nagoya_sakae",
    "ol_shizuoka",
    "ol_hamamatsu",
    "ol_kanazawa_ag",
    "ol_osaka_ekimae",
    "ol_umeda_ag",
    "ol_tenma",
    "ol_shinsaibashi",
    "ol_namba",
    "ol_kyoto",
    "ol_kobe",
    "ol_okayama",
    "ol_hiroshima_ag",
]

# 相席屋 (aisekiya) の Supabase store_id (5店)。ログは src_brand=aisekiya で保存され、
# フロントの slug は store_id とそのまま同じ ("ay_*")。オリエンタルと違い "ol_" 接頭辞を
# 剥がした短縮 slug は使わない（ay_ueno と ol_ueno の衝突を避けるため）。
_FALLBACK_AISEKIYA_STORE_IDS = [
    "ay_shibuya",
    "ay_ikebukuro",
    "ay_ueno",
    "ay_chiba",
    "ay_yokohama",
]


# stores.json から STORE_IDS / AISEKIYA_STORE_IDS を導出する。stores.json の並び順を
# そのまま保持する（build_templates.py の ALL_STORE_IDS 走査や parse_store_slugs()
# の上限打ち切りなど、下流が反復順に依存しているため）。
# 読み込み失敗・JSON 不正・どちらか一方でも空になった場合は上の _FALLBACK_* にフォールバック
# する（新規追加漏れで static list が古いままでも、少なくとも起動時に落ちたり
# 空リストで全店解決不能になったりしない）。
def _load_store_ids_from_stores_json() -> Tuple[list[str], list[str]]:
    rows = load_stores_rows()
    oriental_ids = [
        s["store_id"] for s in rows if s.get("brand") == "oriental" and s.get("store_id")
    ]
    aisekiya_ids = [
        s["store_id"] for s in rows if s.get("brand") == "aisekiya" and s.get("store_id")
    ]
    if not oriental_ids or not aisekiya_ids:
        return list(_FALLBACK_STORE_IDS), list(_FALLBACK_AISEKIYA_STORE_IDS)
    return oriental_ids, aisekiya_ids


STORE_IDS, AISEKIYA_STORE_IDS = _load_store_ids_from_stores_json()

# ブランド横断の全 store_id。store 解決はこれを正とする。
ALL_STORE_IDS = STORE_IDS + AISEKIYA_STORE_IDS

# 相席屋の店舗ごとの総座席数（男女計）。単一ソースは stores.json の各店 `capacity`
# フィールド（= 片性別の座席数）で、総座席数はその ×2。ここではハードコードせず
# stores.json から導出する（フロント frontend/src/app/config/stores.ts と同じ出典に統一）。
# 生の座席レイアウト(tables/vip)は multi_collect.py の AISEKIYA_STORES にあり、
# tests/test_store_capacity_ssot.py が「(tables+vip)*2 == stores.json.capacity」を検証する。
# 読み込み失敗時は空 dict（呼び出し側は既定 80.0 にフォールバックするので安全）。
def _load_aisekiya_total_capacity() -> dict[str, int]:
    result: dict[str, int] = {}
    for s in load_stores_rows():
        if s.get("brand") == "aisekiya":
            cap = s.get("capacity")
            sid = s.get("store_id")
            if sid and isinstance(cap, (int, float)) and cap > 0:
                result[sid] = int(cap) * 2  # 片性別 -> 総座席数
    return result


AISEKIYA_TOTAL_CAPACITY = _load_aisekiya_total_capacity()

# slug -> canonical store_id
#  - オリエンタル: 短縮 slug ("shibuya") -> "ol_shibuya"
#  - 相席屋: slug == store_id ("ay_ueno") -> "ay_ueno"
SLUG_TO_ID = {sid.split("ol_", 1)[-1]: sid for sid in STORE_IDS}
SLUG_TO_ID.update({sid: sid for sid in AISEKIYA_STORE_IDS})

# マルチ店舗系エンドポイント（?stores=slug1,slug2,...）が一度に受け付ける上限。
# 既知の全店舗数（42店舗）を下回らないようにする（全店指定を切り捨てないため）。
# DoS 対策は「既知 slug のみ通す」フィルタとレート制限で担保する。
MAX_MULTI_STORES = len(SLUG_TO_ID)


def parse_store_slugs(
    raw: str | Iterable[str] | None,
    *,
    max_stores: int = MAX_MULTI_STORES,
) -> list[Tuple[str, str]]:
    """`stores=slug1,slug2,...` を (slug, store_id) の列へ正規化する。

    マルチ店舗系エンドポイント（/api/range_multi, /api/forecast_today_multi,
    /api/megribi_score）の共通入口。処理順は
    「小文字化 → 既知 slug のみ残す → 重複除去 → 上限で打ち切り」で固定する:

    - フィルタより先に上限を適用すると、不正 slug が大量に並んだときに末尾の
      正当な slug が落ちる（旧 megribi_score の挙動）。
    - 重複除去をしないと、同じ店舗を2回計算する／レスポンスに同じ店舗が2つ並ぶ
      （旧 forecast_today_multi / megribi_score の挙動）。

    入力順は保持する（下流のスレッド起動順・レスポンス順が入力順に依存するため）。
    """
    if raw is None:
        tokens: list[str] = []
    elif isinstance(raw, str):
        tokens = raw.split(",")
    else:
        tokens = list(raw)

    seen: set[str] = set()
    out: list[Tuple[str, str]] = []
    for part in tokens:
        slug = part.strip().lower()
        if not slug or slug in seen:
            continue
        store_id = SLUG_TO_ID.get(slug)
        if store_id is None:
            continue
        seen.add(slug)
        out.append((slug, store_id))
        if len(out) >= max_stores:
            break
    return out


def resolve_store_identifier_strict(raw: str | None) -> Tuple[str, str] | None:
    """
    Resolve user-provided store slug/id to canonical Supabase store_id, with
    NO fallback to a default store. Returns None when `raw` is empty/missing
    or does not match any known store (unknown slug, or a slug for a store
    that has since closed and been removed from stores.json, e.g. sapporo_ag).

    Used by callers that must distinguish "known store" from "unknown store"
    (e.g. single-store /api/range, where silently falling back to a default
    store_id would leak that default store's data under an unrelated/closed
    slug — see bug #5 in the 2026-07 Fable audit).
    """
    if not raw:
        return None
    candidate = raw.strip()
    if not candidate:
        return None

    # Explicit store_id match (オリエンタル "ol_*" / 相席屋 "ay_*" どちらも)
    if candidate in ALL_STORE_IDS:
        sid = candidate
    else:
        slug = candidate.lower()
        sid = SLUG_TO_ID.get(slug)
        if not sid and slug.startswith("ol_") and slug[3:] in SLUG_TO_ID:
            sid = SLUG_TO_ID[slug[3:]]
        if not sid:
            return None

    slug = sid.split("ol_", 1)[-1]
    return sid, slug


def resolve_store_identifier(raw: str | None, default_id: str) -> Tuple[str, str]:
    """
    Resolve user-provided store slug/id to canonical Supabase store_id.
    Returns (store_id, slug). Falls back to default_id when unknown/empty.

    NOTE: this lenient fallback is intentionally kept for callers where an
    unresolved slug legitimately means "use the configured default store"
    (e.g. /api/forecast_*, /api/second_venues — see oriental/routes/common.py
    resolve_store_id()). For endpoints where an unknown/closed slug must NOT
    silently return another store's data (single-store /api/range), use
    resolve_store_identifier_strict() instead and surface a 404.
    """
    resolved = resolve_store_identifier_strict(raw)
    if resolved is not None:
        return resolved

    sid = default_id
    slug = sid.split("ol_", 1)[-1]
    return sid, slug
