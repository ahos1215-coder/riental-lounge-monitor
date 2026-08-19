"""Storage の「オブジェクトが無い」判定文字列が Flask 側と scripts 側で一致すること。

Supabase Storage は存在しないオブジェクトに対し 404 だけでなく
「HTTP 400 + ボディに not_found 系の文言」を返すことがある。この判定が片系統だけ
古くなると、片方のパイプラインだけが「テンプレ/スナップショット/モデルが無い」を
誤判定し、2026-08-18 の事故と同じ見えにくい壊れ方をする。

2実装が存在するのは、scripts/ が GHA の最小依存環境（flask を install しない）でも
動く必要があり oriental パッケージを import できないため。内容の一致はここで固定する。
"""

from __future__ import annotations

from oriental.clients.supabase import NOT_FOUND_BODY_MARKERS as FLASK_MARKERS
from scripts._supabase_common import NOT_FOUND_BODY_MARKERS as SCRIPTS_MARKERS


def test_両側のnot_found判定文字列が完全一致() -> None:
    assert SCRIPTS_MARKERS == FLASK_MARKERS


def test_現行の判定文字列を固定する() -> None:
    """値そのものを固定する（片方だけ足すと上のテストで気付ける、という二段構え）。"""
    assert FLASK_MARKERS == ("not_found", "not found", "object not found")
