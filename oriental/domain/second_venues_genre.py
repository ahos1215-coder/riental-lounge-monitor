from __future__ import annotations


def map_types_to_genre(types: list[str] | None) -> str:
    """Map Google Place types to MEGRIBI genre labels."""
    if not types:
        return "その他"

    type_set = {t.lower() for t in types if t}

    if "karaoke" in type_set:
        return "カラオケ"
    if {"bar", "pub"} & type_set:
        return "バー"
    if "lodging" in type_set:
        return "ホテル"
    if {"restaurant", "food"} & type_set:
        return "居酒屋"
    if "night_club" in type_set:
        return "クラブ / ライブバー"
    return "その他"
