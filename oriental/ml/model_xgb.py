"""Forecast model wrapper.

Originally XGBoost-only; migrated to LightGBM (2026-04-12) for reduced
inference memory footprint (critical for 76+ models on Render Starter 512MB).
File name kept as model_xgb.py for import compatibility.
"""

from __future__ import annotations

from pathlib import Path

import lightgbm as lgb
import numpy as np

from .preprocess import FEATURE_COLUMNS


class ForecastModel:
    """Inference-only forecast model loaded from pre-trained artifacts.

    Model files are LightGBM boosters (.txt), the only format
    scripts/train_ml_model.py writes.
    """

    def __init__(self, model_men, model_women) -> None:
        self.model_men = model_men
        self.model_women = model_women

    @classmethod
    def from_files(cls, model_men_path: Path, model_women_path: Path) -> "ForecastModel":
        model_men = lgb.Booster(model_file=str(model_men_path))
        model_women = lgb.Booster(model_file=str(model_women_path))
        return cls(model_men=model_men, model_women=model_women)

    def predict(self, features):
        missing = [c for c in FEATURE_COLUMNS if c not in features.columns]
        if missing:
            raise ValueError(f"missing feature columns: {missing}")

        X = features[FEATURE_COLUMNS]

        men_pred = self.model_men.predict(X)
        women_pred = self.model_women.predict(X)

        men_pred = np.maximum(men_pred, 0)
        women_pred = np.maximum(women_pred, 0)
        return men_pred, women_pred
