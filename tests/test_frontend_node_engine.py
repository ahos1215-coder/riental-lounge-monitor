"""Vercel で使う Node.js の版を frontend/package.json で固定していることの番犬（2026-09-26）。

なぜ固定したか:
  Vercel は 2026-10-01 に Node.js 20 を廃止した。それ以降、20 のままのプロジェクトは
  **新しいデプロイがエラーになる**（既存のデプロイは動き続けるので、サイトが落ちるのではなく
  「毎日の自動更新や修正が本番に届かなくなる」形で静かに壊れる）。
  管理画面の設定値はリポジトリから見えないので、`engines.node` で固定した。
  Vercel の公式仕様で、package.json の `engines.node` は管理画面の設定より優先される。

このテストが落ちたら:
  `engines.node` が消えた／20 以下に戻された。消えると管理画面の設定（20 の可能性がある）に
  戻ってしまう。版を上げるのは自由だが、Vercel が提供している版（22.x / 24.x 等）を指定すること。
  scripts/monitor/daily_digest.py の DEADLINES から「Node.js 20 終了」を外した根拠もこの固定。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"


def _engines_node(path: Path, *, lockfile: bool = False) -> str | None:
    data = json.loads(path.read_text(encoding="utf-8"))
    if lockfile:
        data = data.get("packages", {}).get("", {})
    return (data.get("engines") or {}).get("node")


def _major(spec: str) -> int | None:
    # "24.x" / "^24.0.0" / "24" のような「メジャー版を1つに決める」書き方だけを受け付ける。
    # ">=20" のような上限なしの範囲は、将来の版へ勝手に上がるので固定とみなさない。
    m = re.fullmatch(r"\^?(\d+)(\.x|\.\d+\.\d+)?", spec.strip())
    return int(m.group(1)) if m else None


def test_engines_nodeで22以上の版に固定されている() -> None:
    spec = _engines_node(FRONTEND / "package.json")
    assert spec, "frontend/package.json に engines.node が無い（Vercel の管理画面の設定に戻ってしまう）"
    major = _major(spec)
    assert major is not None, f"engines.node はメジャー版を1つに決める書き方にすること（例: 24.x）: {spec!r}"
    assert major >= 22, f"Node.js {major} は Vercel で廃止済み／廃止予定（2026-10-01 に 20 を廃止）: {spec!r}"


def test_lockfileのengines_nodeもpackage_jsonと同じ() -> None:
    assert _engines_node(FRONTEND / "package-lock.json", lockfile=True) == _engines_node(
        FRONTEND / "package.json"
    )
