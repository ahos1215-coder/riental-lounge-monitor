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

SLUG_TO_ID = {sid.split("ol_", 1)[-1]: sid for sid in STORE_IDS}


def resolve_store_identifier(raw: str | None, default_id: str) -> Tuple[str, str]:
    """
    Resolve user-provided store slug/id to canonical Supabase store_id.
    Returns (store_id, slug). Falls back to default_id when unknown/empty.
    """
    if raw:
        candidate = raw.strip()
    else:
        candidate = ""

    # Explicit store_id match
    if candidate in STORE_IDS:
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
