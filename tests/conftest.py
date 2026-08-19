"""pytest 全体の共通設定。

DISABLE_MODEL_PRELOAD=1: create_app() が ENABLE_FORECAST=1 のときに起動する
「モデル事前ロードのバックグラウンドスレッド」をテストでは止める。
このスレッドは Storage(example.supabase.co)への取得失敗を再試行しながら time.sleep() を呼ぶため、
(1) テスト終了後もログを吐き続ける（'I/O operation on closed file'）、
(2) グローバル time.sleep を差し替えるテスト（test_retry_common / test_snapshot_storage_put_retry）に
    1.5 秒の待ち時間が混入してランダムに落ちる（2026-08-19 大整理第3弾で露出）
という順序依存の原因になっていた。プリロード自体の検証は tests/test_stores_json_loader.py が
_preload_models() を直接呼んで行うため、スレッドを止めてもカバレッジは落ちない。
個別のテストが明示的に有効化したい場合は monkeypatch.delenv("DISABLE_MODEL_PRELOAD") で外せる。
"""
from __future__ import annotations

import os

os.environ.setdefault("DISABLE_MODEL_PRELOAD", "1")
