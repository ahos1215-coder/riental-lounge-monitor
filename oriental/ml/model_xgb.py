"""Forecast model wrapper.

Originally XGBoost-only; migrated to LightGBM (2026-04-12) for reduced
inference memory footprint (critical for 76+ models on Render Starter 512MB).
File name kept as model_xgb.py for import compatibility.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .preprocess import FEATURE_COLUMNS

# LightGBM を優先、なければ XGBoost にフォールバック
try:
    import lightgbm as lgb

    _BACKEND = "lightgbm"
except ImportError:
    lgb = None  # type: ignore[assignment]
    _BACKEND = "xgboost"


class ForecastModel:
    """Inference-only forecast model loaded from pre-trained artifacts.

    Supports both LightGBM (.txt) and XGBoost (.json) model files.
    """

    def __init__(self, model_men, model_women) -> None:
        self.model_men = model_men
        self.model_women = model_women

    @classmethod
    def from_files(cls, model_men_path: Path, model_women_path: Path) -> "ForecastModel":
        men_path = str(model_men_path)
        women_path = str(model_women_path)

        if _BACKEND == "lightgbm" and lgb is not None:
            model_men = lgb.Booster(model_file=men_path)
            model_women = lgb.Booster(model_file=women_path)
        else:
            from xgboost import XGBRegressor

            model_men = XGBRegressor(
                n_estimators=100, max_depth=4, learning_rate=0.1,
                subsample=0.8, objective="reg:squarederror",
            )
            model_women = XGBRegressor(
                n_estimators=100, max_depth=4, learning_rate=0.1,
                subsample=0.8, objective="reg:squarederror",
            )
            model_men.load_model(men_path)
            model_women.load_model(women_path)

        return cls(model_men=model_men, model_women=model_women)

    def predict(self, features):
        missing = [c for c in FEATURE_COLUMNS if c not in features.columns]
        if missing:
            raise ValueError(f"missing feature columns: {missing}")

        X = features[FEATURE_COLUMNS]

        if _BACKEND == "lightgbm" and lgb is not None:
            men_pred = self.model_men.predict(X)
            women_pred = self.model_women.predict(X)
        else:
            men_pred = self.model_men.predict(X)
            women_pred = self.model_women.predict(X)

        men_pred = np.maximum(men_pred, 0)
        women_pred = np.maximum(women_pred, 0)
        return men_pred, women_pred
