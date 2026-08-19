"""最小依存環境用の「ファイル直読みローダ」の共有実装（stdlib のみ）。

GHA の一部ジョブ（snapshot / build_templates / weekly など）は stdlib + jpholiday
だけの軽い環境で走る。そこで `from oriental.ml.night_type import ...` と書くと、
`oriental/__init__.py` が flask を、`oriental/ml/__init__.py` が pandas/lightgbm を
引き込んで ModuleNotFoundError になる。そのため対象の .py ファイルだけを
importlib で直接読み込んで代替する、という同じ回避策が3スクリプトに
別々の書き方でコピーされていた。ここに1本化する。

呼び出し側の `try: 通常 import / except ModuleNotFoundError: 直読み` という構造は
各スクリプトに残す（「どの環境で何が起きるか」がその場で読めるようにするため）。

scripts/_supabase_common.py / _night_slots.py と同じ規約で、呼び出し側が
`sys.path.insert(0, <自分のディレクトリ>)` した上でベアインポートする。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def load_module_from_file(name: str, relpath: str):
    """リポジトリルートからの相対パス ``relpath`` の .py を、モジュール名 ``name`` で
    直接読み込んで返す（パッケージの `__init__.py` を一切実行しない）。"""
    path = REPO_ROOT / relpath
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module
