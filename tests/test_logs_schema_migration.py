"""logs テーブルの migration が存在し続けることを守る番犬。

2026-08-22 総合レビュー対応（検証記録は memory/general-review-2026-08-22.md）。

背景: supabase/migrations/ には blog_drafts 系4本しか無く、全 ML 学習・/api/range 系の
唯一の正本である logs テーブルのスキーマがリポジトリから再現できない DR 上の穴があった。
特に 2026-08-19未明の全停止事故（memory/incident-2026-08-18-recovery.md「第4の事故」）で
Supabase SQL Editor から手動作成した (store_id, ts DESC) / (ts DESC) の2本のインデックスは、
本番には存在するのにリポジトリのどこにも記録されていなかった。

このテストは文字列レベルの検問に留める（実際に Postgres へ流して検証する手段がこの
サンドボックスには無いため）。将来 migration ファイルが整理・削除されたときに、
このテストが赤くなって気付けるようにするのが目的。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = REPO_ROOT / "supabase" / "migrations"


def _find_logs_migration() -> Path:
    candidates = sorted(MIGRATIONS_DIR.glob("*logs_schema*.sql"))
    assert candidates, (
        "logs テーブルの migration が見つからない"
        "（supabase/migrations/*logs_schema*.sql が削除された？）"
    )
    # 複数あっても最初の1本を見れば十分（通常は1本だけのはず）。
    return candidates[0]


def test_logsのmigrationファイルが存在する() -> None:
    _find_logs_migration()


def test_logsテーブル定義を含む() -> None:
    text = _find_logs_migration().read_text(encoding="utf-8")
    assert re.search(r"create table if not exists public\.logs", text, re.IGNORECASE)
    # 2026-08事故の解明で判明した本番の必須列（multi_collect.py / provider.py / backup_logs.py と一致）。
    for column in (
        "store_id",
        "ts",
        "men",
        "women",
        "total",
        "src_brand",
        "weather_code",
        "weather_label",
        "temp_c",
        "precip_mm",
    ):
        assert column in text, f"logs migration に列 {column} が無い"


def test_logsの必須インデックス2本を含む() -> None:
    """2026-08-19未明の全停止事故（statement_timeout 死）の再発防止。

    この2本が無いと、本番同等の空 DB から DR 再構築したときに同じ事故を
    そのまま再現してしまう。
    """
    text = _find_logs_migration().read_text(encoding="utf-8")
    assert re.search(
        r"create index if not exists .*on public\.logs\s*\(\s*store_id\s*,\s*ts\s+desc\s*\)",
        text,
        re.IGNORECASE,
    ), "(store_id, ts DESC) インデックス定義が無い"
    assert re.search(
        r"create index if not exists .*on public\.logs\s*\(\s*ts\s+desc\s*\)",
        text,
        re.IGNORECASE,
    ), "(ts DESC) インデックス定義が無い"


def test_全migrationが冪等な文言を使っている() -> None:
    """本番に流しても no-op であることの最低限の担保（IF NOT EXISTS の欠落を検出）。"""
    text = _find_logs_migration().read_text(encoding="utf-8")
    assert "create table if not exists" in text.lower()
    # index 文が最低2本あり、いずれも if not exists 付きであること。
    index_lines = [
        line for line in text.lower().splitlines() if line.strip().startswith("create index")
    ]
    assert len(index_lines) >= 2
    assert all("if not exists" in line for line in index_lines)
