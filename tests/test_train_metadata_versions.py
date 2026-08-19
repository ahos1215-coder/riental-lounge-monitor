"""学習 metadata.json に記録するライブラリバージョンの番犬（B-04）。

本番の学習器は LightGBM（`model_format: "lightgbm"`）なのに、metadata には
`xgboost_version` しか無かった。`lightgbm_version` を追加（additive）し、
`xgboost_version` は既存 metadata との互換のため残す。

model_registry._validate_metadata が見るのは schema_version / feature_columns
だけなので、キー追加は予測経路に影響しない。
"""

from __future__ import annotations

import pandas as pd

import scripts.train_ml_model as train_ml_model
from scripts.train_ml_model import TrainingConfig, _build_metadata


def _training_cfg() -> TrainingConfig:
    return TrainingConfig(
        supabase_url="https://example.supabase.co",
        supabase_service_key="dummy-key",
        bucket="ml-models",
        prefix="forecast/latest",
        schema_version="v7",
        timezone="Asia/Tokyo",
        train_days=180,
        train_limit=1_000_000,
        store_id=None,
        sample_weight_peak=1.8,
        sample_weight_rain=1.8,
        optuna_trials=30,
        optuna_enabled=True,
        objective="regression",
        optuna_max_rows=0,
        gate_max_regression_pct=20.0,
        stale_store_days=7.0,
        recency_halflife_days=90.0,
        recency_floor=0.5,
    )


def _metadata() -> dict:
    return _build_metadata(
        _training_cfg(),
        pd.DataFrame({"total": [1, 2, 3]}),
        trained_at="2026-08-19T00:00:00+09:00",
        date_tag="20260819",
        store_models={},
    )


def test_metadataは学習器がlightgbmであることを示す():
    meta = _metadata()
    assert meta["model_format"] == "lightgbm"
    assert meta["model_men"].endswith(".txt")
    assert meta["model_women"].endswith(".txt")


def test_lightgbmのバージョンが記録される():
    meta = _metadata()
    assert meta["lightgbm_version"] == train_ml_model.lgb.__version__


def test_xgboost_versionは互換のため残っている():
    """読み手は現状いないが、過去の metadata.json と形を揃えるため残置する。"""
    meta = _metadata()
    assert meta["xgboost_version"] == train_ml_model.xgb.__version__


def test_schema_versionとfeature_columnsは従来どおり():
    """model_registry._validate_metadata が見る2キーが変わっていないこと。"""
    meta = _metadata()
    assert meta["schema_version"] == "v7"
    assert isinstance(meta["feature_columns"], list) and meta["feature_columns"]
