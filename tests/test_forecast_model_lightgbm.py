"""ForecastModel(oriental/ml/model_xgb.py)の直接ユニットテスト。

ファイル名は model_xgb.py だが中身は LightGBM（2026-04-12 移行済み・改名禁止）。
XGBoost フォールバック分岐を削除する前後で、以下が変わらないことを固定する:
  - LightGBM の .txt モデルを from_files で読める
  - predict が (men, women) の 2 本を返し、負値は 0 にクリップされる
  - FEATURE_COLUMNS が欠けていれば ValueError
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from oriental.ml.model_xgb import ForecastModel
from oriental.ml.preprocess import FEATURE_COLUMNS


def _train_dummy_booster(tmp_path, name: str, target_sign: float):
    """FEATURE_COLUMNS を入力に取る極小の LightGBM Booster を学習して .txt に保存する。"""
    lgb = pytest.importorskip("lightgbm")
    rng = np.random.default_rng(0)
    X = pd.DataFrame(
        rng.normal(size=(64, len(FEATURE_COLUMNS))),
        columns=FEATURE_COLUMNS,
    )
    y = target_sign * (X[FEATURE_COLUMNS[0]].to_numpy() * 10.0 + 5.0)
    booster = lgb.train(
        {"objective": "regression", "verbose": -1, "min_data_in_leaf": 1, "num_leaves": 3},
        lgb.Dataset(X, label=y),
        num_boost_round=3,
    )
    path = tmp_path / f"model_{name}.txt"
    booster.save_model(str(path))
    return path, X


def test_from_files_loads_lightgbm_txt_and_predicts(tmp_path):
    men_path, X = _train_dummy_booster(tmp_path, "men", 1.0)
    # women 側はわざと負の目標値で学習し、predict のゼロクリップが効くことを見る。
    women_path, _ = _train_dummy_booster(tmp_path, "women", -1.0)

    model = ForecastModel.from_files(men_path, women_path)
    men_pred, women_pred = model.predict(X)

    assert len(men_pred) == len(X)
    assert len(women_pred) == len(X)
    assert (men_pred >= 0).all()
    assert (women_pred >= 0).all()
    # 負の目標値で学習した women 側は、クリップの結果 0 が含まれるはず。
    assert (women_pred == 0).any()


def test_predict_rejects_missing_feature_columns(tmp_path):
    men_path, X = _train_dummy_booster(tmp_path, "men", 1.0)
    women_path, _ = _train_dummy_booster(tmp_path, "women", 1.0)
    model = ForecastModel.from_files(men_path, women_path)

    with pytest.raises(ValueError) as exc:
        model.predict(X.drop(columns=[FEATURE_COLUMNS[0]]))
    assert FEATURE_COLUMNS[0] in str(exc.value)
