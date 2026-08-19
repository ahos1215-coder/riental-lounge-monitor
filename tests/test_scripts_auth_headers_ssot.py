"""Supabase 認証ヘッダの単一ソース番犬（scripts 側）。

背景: 「service role key は `apikey` と `Authorization: Bearer` の両方に入れる」という
約束は、片方が欠けると Supabase が 401 を返す。この辞書が scripts/ 配下15箇所に手書きで
コピーされていたため、次に事故が起きたとき直す場所が15箇所に散っていた。

ここで守ること:
  1) scripts 側 `_supabase_common.auth_headers` と Flask 側
     `oriental/clients/supabase.auth_headers` が**全フラグ組み合わせで同一の辞書**を返す
     （2実装あるのは、scripts/ が GHA の最小依存環境で oriental パッケージを import
     できないという事情によるもので、内容が食い違ってよい理由ではない）。
  2) 本番 scripts に `"apikey"` のリテラルが再び生えないこと
     （実験・デバッグ用の scripts/experiments・scripts/debug・scripts/dev は対象外）。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from oriental.clients.supabase import auth_headers as flask_auth_headers
from scripts._supabase_common import auth_headers as scripts_auth_headers

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"

# 認証ヘッダの単一ソース。ここだけがリテラルを持ってよい。
ALLOWED_FILES = {"_supabase_common.py"}
# 本番経路ではないディレクトリ（実験・デバッグ・使い捨て）。
EXCLUDED_DIRS = {"experiments", "debug", "dev", "__pycache__"}


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"accept_json": True},
        {"content_type": True},
        {"accept_json": True, "content_type": True},
    ],
)
def test_scripts側とFlask側のauth_headersが完全一致(kwargs) -> None:
    key = "service-role-key"
    assert scripts_auth_headers(key, **kwargs) == flask_auth_headers(key, **kwargs)


def test_auth_headersはapikeyとBearerの両方を入れる() -> None:
    headers = scripts_auth_headers("k")
    assert headers["apikey"] == "k"
    assert headers["Authorization"] == "Bearer k"


def _production_scripts() -> list[Path]:
    out: list[Path] = []
    for path in sorted(SCRIPTS.rglob("*.py")):
        rel = path.relative_to(SCRIPTS)
        if set(rel.parts[:-1]) & EXCLUDED_DIRS:
            continue
        out.append(path)
    return out


def test_本番scriptsにapikeyリテラルの手書きが無い() -> None:
    """新しい REST 呼び出しを書くときは `_supabase_common.auth_headers` を使うこと。"""
    files = _production_scripts()
    assert files, "scripts/ 配下の .py が見つからない（パス誤り）"
    offenders: list[str] = []
    for path in files:
        if path.name in ALLOWED_FILES:
            continue
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r'"apikey"', text):
            line = text[: match.start()].count("\n") + 1
            offenders.append(f"{path.relative_to(REPO_ROOT).as_posix()}:{line}")
    assert offenders == [], (
        "認証ヘッダの手書きが残っている（_supabase_common.auth_headers を使う）: "
        f"{offenders}"
    )
