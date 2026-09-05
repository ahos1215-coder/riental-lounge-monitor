"""閉店店舗 slug の二重管理を番犬で縛る（2026-09-06）。

■ 閉店店舗を増やすときの手順（ここが手順書本体）
  1. frontend/src/data/stores.json から該当店舗の行を消す（店舗マスタの正本）。
  2. oriental/utils/stores.py の _FALLBACK_STORE_IDS / _FALLBACK_AISEKIYA_STORE_IDS を
     stores.json に合わせる（tests/test_store_id_ssot.py が検問する）。
  3. **frontend/src/proxy.ts の CLOSED_STORE_SLUGS に slug を追記する**（410 Gone の正本）。
  4. **scripts/analytics_weekly_report.py の CLOSED_STORE_SLUGS にも同じ slug を追記する**
     （週次アナリティクスのページ分類用の写し）。
  3 と 4 は手書きの複製なので、片方だけ直すとこのテストが落ちる。

■ なぜ必要か
  2026-07-08 に新潟店を stores.json から消したのに、410 を返す proxy.ts の登録は
  2026-08-20 まで **43日空いた**。その間 /store/ay_niigata は 404 を返し続け、
  検索から来た実利用者（GSC実測で90日 193表示・21クリック・平均6.5位）が着地に失敗し、
  Google のインデックスからも遅れてしか消えなかった。

■ このテストが見ていないこと（できないので書かない）
  「stores.json から消えた店を自動で検知して CLOSED_STORE_SLUGS への追記を強制する」ことは、
  過去の店舗一覧をリポジトリが持っていない以上できない。ここで固定できるのは
  (a) 2つの CLOSED_STORE_SLUGS が一致していること、
  (b) 閉店扱いの slug が店舗マスタ側に残っていないこと（閉店したのにマスタに居る、の逆パターン）
  の2点だけ。上の手順 3・4 は人間が守る前提で、ズレたらここが落ちる。

ネットワークアクセスなし。実ソースファイルを読むだけ。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from oriental.utils.stores import ALL_STORE_IDS
from scripts.analytics_weekly_report import CLOSED_STORE_SLUGS as PY_CLOSED_SLUGS

REPO_ROOT = Path(__file__).resolve().parents[1]
PROXY_TS_PATH = REPO_ROOT / "frontend" / "src" / "proxy.ts"
STORES_JSON_PATH = REPO_ROOT / "frontend" / "src" / "data" / "stores.json"


def _extract_ts_closed_slugs() -> list[str]:
    """proxy.ts の `const CLOSED_STORE_SLUGS = new Set([...])` から文字列リテラルだけ抜く。

    tests/test_analytics_event_parity.py と同じ流儀（TS をパースせず正規表現で読む軽量な方法）。
    """
    text = PROXY_TS_PATH.read_text(encoding="utf-8")
    m = re.search(r"CLOSED_STORE_SLUGS\s*=\s*new Set\(\s*\[(.*?)\]\s*\)", text, re.DOTALL)
    assert m is not None, (
        "const CLOSED_STORE_SLUGS = new Set([...]) が frontend/src/proxy.ts に見つかりません"
        "（書き方を変えた場合はこのテストの正規表現も直してください）。"
    )
    return re.findall(r'"([a-zA-Z0-9_]+)"', m.group(1))


def _stores_json_slugs() -> set[str]:
    rows = json.loads(STORES_JSON_PATH.read_text(encoding="utf-8"))
    return {r["slug"] for r in rows if r.get("slug")}


def test_proxy_ts_file_exists():
    assert PROXY_TS_PATH.is_file(), f"frontend/src/proxy.ts が見つかりません: {PROXY_TS_PATH}"


def test_ts_closed_slugs_have_no_duplicates():
    ts_slugs = _extract_ts_closed_slugs()
    assert len(ts_slugs) == len(set(ts_slugs)), "proxy.ts の CLOSED_STORE_SLUGS に重複があります。"


def test_ts_and_python_closed_slugs_match():
    """410 の正本(proxy.ts)と写し(analytics_weekly_report.py)が完全一致すること。"""
    ts_slugs = set(_extract_ts_closed_slugs())
    py_slugs = set(PY_CLOSED_SLUGS)
    only_ts = ts_slugs - py_slugs
    only_py = py_slugs - ts_slugs
    assert not only_ts and not only_py, (
        "閉店店舗 slug の2つの一覧がズレています。閉店処理では frontend/src/proxy.ts と "
        "scripts/analytics_weekly_report.py の **両方** に追記してください。"
        f" proxy.ts だけにある: {sorted(only_ts)} /"
        f" analytics_weekly_report.py だけにある: {sorted(only_py)}"
    )


def test_closed_slugs_are_absent_from_stores_json():
    """閉店扱いの slug が店舗マスタ（stores.json）に残っていないこと。"""
    still_listed = sorted(set(_extract_ts_closed_slugs()) & _stores_json_slugs())
    assert not still_listed, (
        "閉店扱いなのに frontend/src/data/stores.json に残っている店舗があります: "
        f"{still_listed}。閉店なら stores.json から消す、営業中なら CLOSED_STORE_SLUGS から外す、"
        "のどちらかに揃えてください（今のままだと 410 と一覧表示が矛盾します）。"
    )


def test_closed_slugs_are_absent_from_all_store_ids():
    """閉店扱いの slug が oriental 側の ALL_STORE_IDS にも残っていないこと。

    slug と store_id は表記が違う（例: shibuya -> ol_shibuya、ay_ 系はそのまま）ため、
    両方の綴りで確認する。
    """
    all_ids = set(ALL_STORE_IDS)
    leftovers = sorted(
        slug for slug in _extract_ts_closed_slugs()
        if slug in all_ids or f"ol_{slug}" in all_ids
    )
    assert not leftovers, (
        "閉店扱いなのに oriental/utils/stores.py::ALL_STORE_IDS に残っている店舗があります: "
        f"{leftovers}。stores.json と _FALLBACK_* の両方から消してください"
        "（残っていると収集・ML・監視が閉店店舗を期待し続けます）。"
    )
