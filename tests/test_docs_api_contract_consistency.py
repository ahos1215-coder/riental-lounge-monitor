"""番犬: 入口文書が `/api/range` の契約と矛盾しないこと（外部レビュー F15）。

2026-08-21 の外部レビューで「入口文書が現役 API 契約と分裂している」と指摘された。
実装（`oriental/routes/data_range.py::_parse_range_query`）は `from` / `to` を
**日付粒度の任意パラメータ**として正式に受けるのに、README / plan/INDEX /
plan/CODEx_PROMPTS / plan/ARCHITECTURE は「クエリ追加禁止」と断言していた。

このテストは実装を正とし、
  (1) `from`/`to` を受け付ける実装が残り続けること
  (2) 入口文書に「from/to の追加は禁止」系の断言が復活しないこと
  (3) 契約の正本（CLAUDE.md §3）への参照が入口文書に残ること
を固定する。あわせて、2025年の旧 Next.js プロトタイプがリポジトリ直下に
戻ってこないことも見る（初見の人間/AI が現役実装と誤認する原因だった）。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from oriental import create_app
from oriental.routes.data_range import _parse_range_query

REPO_ROOT = Path(__file__).resolve().parents[1]

# 「入口」と位置づけている文書（CLAUDE.md は正本なので対象外＝ここだけが詳細を書いてよい）
#
# 2026-08-21 追記: 当初この4本だけを見ていたが、`plan/API_CONTRACT.md`（詳細な API 仕様書）と
# `plan/API_CURRENT.md`（それを参照する補足メモ）はどちらも対象外だった。README 等の
# 「トップレベルの入口」だけを ENTRY_DOCS と呼んでいたため、その先に読み進めた先にある
# 詳細仕様書が漏れた——「入口文書を直せば十分」という思い込みの穴で、この2本には
# 同じ「from/to は公開契約に含めない」という誤った断言が独立に残っており、13件緑のまま
# すり抜けていた（外部レビュー F15・第3ラウンド）。詳細仕様書ほど誤読の実害が大きい
# （外部レビュアーが2ラウンド連続でここを引用して誤読した）ため、以後は ENTRY_DOCS に含める。
ENTRY_DOCS = (
    REPO_ROOT / "README.md",
    REPO_ROOT / "plan" / "INDEX.md",
    REPO_ROOT / "plan" / "CODEx_PROMPTS.md",
    REPO_ROOT / "plan" / "ARCHITECTURE.md",
    REPO_ROOT / "plan" / "API_CONTRACT.md",
    REPO_ROOT / "plan" / "API_CURRENT.md",
)

# 復活してはいけない断言（実装と矛盾する）
FORBIDDEN_PHRASES = (
    "from/to などの追加は禁止",
    "クエリ追加・サーバ側時間フィルタ禁止",
    "新規クエリ追加禁止",
    "`store` + `limit` のみ",
    "store + limit のみ",
    "`store` / `limit` のみ",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------- (1) 実装が正 ----------


def test_実装はfrom_toを日付粒度の任意パラメータとして受ける():
    app = create_app()
    with app.test_request_context("/api/range?store=shibuya&from=2026-08-01&to=2026-08-03&limit=10"):
        query = _parse_range_query(app.config["APP_CONFIG"])
    assert query.start == date(2026, 8, 1)
    assert query.end == date(2026, 8, 3)


# ---------- (2)(3) 入口文書 ----------


@pytest.mark.parametrize("doc", ENTRY_DOCS, ids=lambda p: p.name)
def test_入口文書にfrom_to禁止の断言が復活しない(doc: Path):
    text = _read(doc)
    for phrase in FORBIDDEN_PHRASES:
        assert phrase not in text, f"{doc.name} に実装と矛盾する断言が残っています: {phrase}"


@pytest.mark.parametrize("doc", ENTRY_DOCS, ids=lambda p: p.name)
def test_入口文書は契約の正本としてCLAUDE_mdを指す(doc: Path):
    assert "CLAUDE.md" in _read(doc), f"{doc.name} が契約の正本（CLAUDE.md §3）を参照していません"


def test_plan_readmeの読了順にARCHITECTUREが二重に出てこない():
    lines = [
        ln for ln in _read(REPO_ROOT / "plan" / "README.md").splitlines()
        if "`ARCHITECTURE.md`**" in ln
    ]
    assert len(lines) == 1, f"読了順に ARCHITECTURE.md が {len(lines)} 回出ています"


def test_ARCHITECTUREのDaily失敗時挙動が実装のcarry_overと一致する():
    """実装（scripts/local_report_job.py::_apply_carry_over_or_fail）は3状態の
    carry-over 方式。ARCHITECTURE.md はこれを「本文空・非公開・error あり」の
    1状態としか書いておらず矛盾していた（外部レビュー F15）。
    """
    job_src = _read(REPO_ROOT / "scripts" / "local_report_job.py")
    assert "def _apply_carry_over_or_fail" in job_src, "carry-over 実装が消えています"

    arch = _read(REPO_ROOT / "plan" / "ARCHITECTURE.md")
    assert "carry-over" in arch
    assert "_apply_carry_over_or_fail" in arch
    # 「失敗＝必ず本文空・非公開」という旧記述が復活していないこと
    assert "失敗時は本文空 + is_published=false" not in arch


# ---------- 旧プロトタイプ ----------


def test_旧Nextプロトタイプはリポジトリ直下に戻ってこない():
    assert not (REPO_ROOT / "app" / "page.tsx").exists()
    assert not (REPO_ROOT / "app" / "api" / "forecast" / "route.ts").exists()
    assert not (REPO_ROOT / "tailwind.config.js").exists()
    # 削除ではなく archive/ へ退避してある
    archived = REPO_ROOT / "archive" / "next_prototype_2025"
    assert (archived / "app" / "page.tsx").exists()
    assert (archived / "tailwind.config.js").exists()
    assert "next_prototype_2025" in _read(REPO_ROOT / "archive" / "README.md")


def test_現役フロントのtailwind設定はfrontend配下に残っている():
    assert (REPO_ROOT / "frontend" / "tailwind.config.js").exists()
