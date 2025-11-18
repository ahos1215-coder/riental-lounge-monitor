from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

import numpy as np
import pandas as pd
from xgboost import XGBRegressor

@dataclass
class QuantileBand:
    low: float
    high: float

class _OneTargetModel:
    """1系列（men / women）用のXGB + CQR 実装"""
    def __init__(self, objective: str = "count:poisson", random_state: int = 42):
        self.model = XGBRegressor(
            objective=objective,
            tree_method="hist",
            n_estimators=400,
            max_depth=6,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=random_state,
            n_jobs=0,
        )
        # 予測帯（CQR）用の下限/上限オフセット（初期値は狭め）
        self.band = QuantileBand(low=-1.0, high=1.0)

    def fit(self, X: pd.DataFrame, y: pd.Series, X_val: pd.DataFrame, y_val: pd.Series):
        # p50 学習
        self.model.fit(X, y)
        # バリデーション残差の分位で帯を作る（非常に軽量なCQR）
        p50 = self.model.predict(X_val)
        resid = (y_val.values - p50)
        self.band = QuantileBand(
            low=float(np.quantile(resid, 0.10)),
            high=float(np.quantile(resid, 0.90)),
        )

    def predict_p50(self, X: pd.DataFrame) -> np.ndarray:
        return self.model.predict(X)

    def predict_interval(self, X: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        p50 = self.predict_p50(X)
        p10 = p50 + self.band.low
        p90 = p50 + self.band.high
        # 人数なので0未満は0にクリップ
        return np.clip(p10, 0, None), np.clip(p50, 0, None), np.clip(p90, 0, None)

    def save(self, dirpath: Path, name: str):
        dirpath.mkdir(parents=True, exist_ok=True)
        self.model.save_model(str(dirpath / f"{name}_model.json"))
        (dirpath / f"{name}_cqr.json").write_text(
            json.dumps({"low": self.band.low, "high": self.band.high}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load(self, dirpath: Path, name: str):
        self.model.load_model(str(dirpath / f"{name}_model.json"))
        d = json.loads((dirpath / f"{name}_cqr.json").read_text(encoding="utf-8"))
        self.band = QuantileBand(low=float(d["low"]), high=float(d["high"]))

class ModelService:
    """men / women の2系列を別モデルで持つ薄いサービス層"""
    def __init__(self):
        self.men = _OneTargetModel()
        self.women = _OneTargetModel()

    def fit(self, X_train: pd.DataFrame, y_men: pd.Series, y_women: pd.Series,
            X_val: pd.DataFrame, y_men_val: pd.Series, y_women_val: pd.Series):
        self.men.fit(X_train, y_men, X_val, y_men_val)
        self.women.fit(X_train, y_women, X_val, y_women_val)

    def predict_interval(self, X: pd.DataFrame):
        m10, m50, m90 = self.men.predict_interval(X)
        w10, w50, w90 = self.women.predict_interval(X)
        t10, t50, t90 = m10 + w10, m50 + w50, m90 + w90
        return (m10, m50, m90), (w10, w50, w90), (t10, t50, t90)

    def save(self, dirpath: Path):
        self.men.save(dirpath, "men")
        self.women.save(dirpath, "women")

    def load(self, dirpath: Path):
        self.men.load(dirpath, "men")
        self.women.load(dirpath, "women")
