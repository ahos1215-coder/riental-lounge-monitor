from __future__ import annotations

from typing import Tuple

# Known Supabase store_ids (38 stores). Kept minimal (id/slug) to avoid duplicating store metadata.
STORE_IDS = [
    "ol_nagasaki",
    "ol_fukuoka",
    "ol_kokura",
    "ol_oita",
    "ol_kumamoto",
    "ol_miyazaki",
    "ol_kagoshima",
    "ol_okinawa_ag",
    "ol_gangnam",
    "ol_sapporo_ag",
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

# 相席屋 (aisekiya) の Supabase store_id (6店)。ログは src_brand=aisekiya で保存され、
# フロントの slug は store_id とそのまま同じ ("ay_*")。オリエンタルと違い "ol_" 接頭辞を
# 剥がした短縮 slug は使わない（ay_ueno と ol_ueno の衝突を避けるため）。
AISEKIYA_STORE_IDS = [
    "ay_shibuya",
    "ay_ikebukuro",
    "ay_ueno",
    "ay_chiba",
    "ay_yokohama",
    "ay_niigata",
]

# ブランド横断の全 store_id。store 解決はこれを正とする。
ALL_STORE_IDS = STORE_IDS + AISEKIYA_STORE_IDS

# 相席屋の店舗ごとの総座席数（男女計）。multi_collect.py の AISEKIYA_STORES
# ((tables + vip) * 2 = 片性別の座席数) と同じ値を総座席数として持つ
# （= (tables + vip) * 4）。multi_collect.py 側を更新したらここも同期すること。
# multi_collect.py はスクレイピング用スクリプトで import 時の副作用が大きいため、
# ここに最小限のコピーを持つ方が安全（Flask アプリからは import しない）。
AISEKIYA_TOTAL_CAPACITY = {
    "ay_shibuya": 76,
    "ay_ikebukuro": 56,
    "ay_ueno": 60,
    "ay_chiba": 88,
    "ay_yokohama": 68,
    "ay_niigata": 60,
}

# slug -> canonical store_id
#  - オリエンタル: 短縮 slug ("shibuya") -> "ol_shibuya"
#  - 相席屋: slug == store_id ("ay_ueno") -> "ay_ueno"
SLUG_TO_ID = {sid.split("ol_", 1)[-1]: sid for sid in STORE_IDS}
SLUG_TO_ID.update({sid: sid for sid in AISEKIYA_STORE_IDS})


def resolve_store_identifier(raw: str | None, default_id: str) -> Tuple[str, str]:
    """
    Resolve user-provided store slug/id to canonical Supabase store_id.
    Returns (store_id, slug). Falls back to default_id when unknown/empty.
    """
    if raw:
        candidate = raw.strip()
    else:
        candidate = ""

    # Explicit store_id match (オリエンタル "ol_*" / 相席屋 "ay_*" どちらも)
    if candidate in ALL_STORE_IDS:
        sid = candidate
    else:
        slug = candidate.lower()
        sid = SLUG_TO_ID.get(slug)
        if not sid and slug.startswith("ol_") and slug[3:] in SLUG_TO_ID:
            sid = SLUG_TO_ID[slug[3:]]
        if not sid:
            sid = default_id

    slug = sid.split("ol_", 1)[-1]
    return sid, slug
