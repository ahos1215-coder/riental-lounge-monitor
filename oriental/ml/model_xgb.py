from __future__ import annotations

from pathlib import Path

import numpy as np
from xgboost import XGBRegressor

from .preprocess import FEATURE_COLUMNS


class ForecastModel:
    """Inference-only forecast model loaded from pre-trained artifacts."""

    def __init__(self, model_men: XGBRegressor, model_women: XGBRegressor) -> None:
        self.model_men = model_men
        self.model_women = model_women

    @staticmethod
    def _build_model() -> XGBRegressor:
        return XGBRegressor(
            n_estimators=100,
            max_depth=4,
            learning_rate=0.1,
            subsample=0.8,
            objective="reg:squarederror",
        )

    @classmethod
    def from_files(cls, model_men_path: Path, model_women_path: Path) -> "ForecastModel":
        model_men = cls._build_model()
        model_women = cls._build_model()
        model_men.load_model(str(model_men_path))
        model_women.load_model(str(model_women_path))
        return cls(model_men=model_men, model_women=model_women)

    def predict(self, features):
        missing = [c for c in FEATURE_COLUMNS if c not in features.columns]
        if missing:
            raise ValueError(f"missing feature columns: {missing}")
        men_pred = self.model_men.predict(features[FEATURE_COLUMNS])
        women_pred = self.model_women.predict(features[FEATURE_COLUMNS])
        men_pred = np.maximum(men_pred, 0)
        women_pred = np.maximum(women_pred, 0)
        return men_pred, women_pred
