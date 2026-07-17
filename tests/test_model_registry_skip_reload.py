"""model_registry の「変更なし refresh はモデル再構築をスキップ」の回帰テスト。

2026-07-17 メモリ成長事件#2: refresh_sec(900s)毎に同一モデルを再DL+再パースし、
glibc arena断片化でRSSが単調増加していた。モデルファイル名(学習日付入りで一意)が
前回ロードと同じ場合は既存Boosterを使い続けることを保証する。
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from oriental.ml import model_registry as mr


class _FakeModel:
    pass


@pytest.fixture
def registry(tmp_path, monkeypatch):
    reg = mr.ForecastModelRegistry(
        supabase_url="https://example.supabase.co",
        service_role_key="test-key",
        bucket="ml-models",
        model_prefix="forecast/latest",
        schema_version="v7",
        cache_dir=tmp_path,
        refresh_sec=900,
        request_timeout_sec=5.0,
        download_retry=1,
        logger=__import__("logging").getLogger("test"),
    )
    meta = {
        "schema_version": "v7",
        "has_store_models": True,
        "store_models": {
            "ol_shibuya": {
                "model_men": "model_ol_shibuya_20260716_men.txt",
                "model_women": "model_ol_shibuya_20260716_women.txt",
            }
        },
    }
    calls = {"download": 0, "from_files": 0, "meta": dict(meta)}

    monkeypatch.setattr(reg, "_download_to_cache", lambda name, path: calls.__setitem__("download", calls["download"] + 1))
    monkeypatch.setattr(reg, "_load_metadata", lambda path: dict(calls["meta"]))
    monkeypatch.setattr(reg, "_validate_metadata", lambda m: None)
    monkeypatch.setattr(
        mr.ForecastModel, "from_files",
        classmethod(lambda cls, *, model_men_path, model_women_path:
                    (calls.__setitem__("from_files", calls["from_files"] + 1) or _FakeModel())),
    )
    return reg, calls


def test_unchanged_names_skip_model_reload(registry):
    reg, calls = registry
    b1 = reg.get_bundle(store_id="ol_shibuya")
    assert calls["from_files"] == 1
    # refresh期限を強制的に切らせて再取得 → 名前が同じなのでBooster再構築なし・同一bundle
    reg._next_refresh_unix = 0.0
    b2 = reg.get_bundle(store_id="ol_shibuya")
    assert calls["from_files"] == 1, "モデル名が不変ならfrom_filesは再実行されない"
    assert b2 is b1, "既存bundleオブジェクトを使い続ける"


def test_changed_names_trigger_reload(registry):
    reg, calls = registry
    reg.get_bundle(store_id="ol_shibuya")
    assert calls["from_files"] == 1
    # 日次再学習後を模擬: メタデータのモデル名が新しい日付に変わる
    calls["meta"]["store_models"]["ol_shibuya"] = {
        "model_men": "model_ol_shibuya_20260717_men.txt",
        "model_women": "model_ol_shibuya_20260717_women.txt",
    }
    reg._next_refresh_unix = 0.0
    b2 = reg.get_bundle(store_id="ol_shibuya")
    assert calls["from_files"] == 2, "モデル名が変わったら再構築される"
    assert b2.model_names == ("model_ol_shibuya_20260717_men.txt", "model_ol_shibuya_20260717_women.txt")


def test_metadata_shared_across_bundles(registry):
    """同一内容のメタデータは全bundleで1オブジェクトを共有する(43部コピー~26MBの排除)。"""
    reg, calls = registry
    calls["meta"]["store_models"]["ol_ueno"] = {
        "model_men": "model_ol_ueno_20260716_men.txt",
        "model_women": "model_ol_ueno_20260716_women.txt",
    }
    b1 = reg.get_bundle(store_id="ol_shibuya")
    reg._next_refresh_unix = 0.0
    b2 = reg.get_bundle(store_id="ol_ueno")
    assert b1.metadata is b2.metadata, "内容同一ならmetadata dictは共有される"
