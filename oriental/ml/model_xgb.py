from __future__ import annotations

import numpy as np
from xgboost import XGBRegressor

from .preprocess import FEATURE_COLUMNS


class ForecastModel:
    def __init__(self) -> None:
        self.model_men = self._build_model()
        self.model_women = self._build_model()
        self.is_trained = False
        self.fallback_men = 0.0
        self.fallback_women = 0.0

    @staticmethod
    def _build_model() -> XGBRegressor:
        return XGBRegressor(
            n_estimators=100,
            max_depth=4,
            learning_rate=0.1,
            subsample=0.8,
            objective="reg:squarederror",
        )

    def fit(self, features, men, women) -> None:
        if len(features) < 20:
            self.fallback_men = float(np.mean(men)) if len(men) else 0.0
            self.fallback_women = float(np.mean(women)) if len(women) else 0.0
            self.is_trained = False
            return
        self.model_men.fit(features[FEATURE_COLUMNS], men)
        self.model_women.fit(features[FEATURE_COLUMNS], women)
        self.is_trained = True

    def predict(self, features):
        if not self.is_trained:
            men_pred = np.full(len(features), self.fallback_men)
            women_pred = np.full(len(features), self.fallback_women)
        else:
            men_pred = self.model_men.predict(features[FEATURE_COLUMNS])
            women_pred = self.model_women.predict(features[FEATURE_COLUMNS])
        men_pred = np.maximum(men_pred, 0)
        women_pred = np.maximum(women_pred, 0)
        return men_pred, women_pred
