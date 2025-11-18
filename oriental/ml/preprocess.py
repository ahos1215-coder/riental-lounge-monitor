from __future__ import annotations

import numpy as np
import pandas as pd

FEATURE_COLUMNS = [
    "hour",
    "minute",
    "dow",
    "is_weekend",
    "sin_time",
    "cos_time",
    "men_lag_1",
    "men_lag_2",
    "men_lag_4",
    "men_ma_2",
    "men_ma_4",
    "women_lag_1",
    "women_lag_2",
    "women_lag_4",
    "women_ma_2",
    "women_ma_4",
]


def prepare_dataframe(records: list[dict], tz: str) -> pd.DataFrame:
    df = pd.DataFrame(records)
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce").dt.tz_convert(tz)
    df = df.dropna(subset=["ts"]).sort_values("ts")
    df["men"] = df["men"].fillna(0)
    df["women"] = df["women"].fillna(0)
    df["total"] = df["total"].fillna(df["men"] + df["women"])
    return add_time_features(df)


def add_time_features(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    df["hour"] = df["ts"].dt.hour
    df["minute"] = df["ts"].dt.minute
    df["dow"] = df["ts"].dt.dayofweek
    df["is_weekend"] = df["dow"].isin([4, 5]).astype(int)
    minutes = df["hour"] * 60 + df["minute"]
    df["sin_time"] = np.sin(2 * np.pi * minutes / 1440)
    df["cos_time"] = np.cos(2 * np.pi * minutes / 1440)
    for lag in (1, 2, 4):
        df[f"men_lag_{lag}"] = df["men"].shift(lag)
        df[f"women_lag_{lag}"] = df["women"].shift(lag)
    for win in (2, 4):
        df[f"men_ma_{win}"] = df["men"].rolling(win, min_periods=1).mean()
        df[f"women_ma_{win}"] = df["women"].rolling(win, min_periods=1).mean()
    df = df.fillna(method="bfill").fillna(method="ffill")
    return df
def build_features(df: pd.DataFrame, tz: str) -> pd.DataFrame:
    """
    学習/推論で共通の特徴量生成。
    入力: df は ["ts","men","women","total"] を含むこと。
    - ts を tz-aware に正規化
    - 欠損は前後埋め
    - add_time_features(...) を適用
    戻り値: 特徴量列を含む DataFrame（FEATURE_COLUMNS をこの中から参照）
    """
    if df is None or df.empty:
        return df
    out = df.copy()
    out["ts"] = pd.to_datetime(out["ts"], utc=True, errors="coerce").dt.tz_convert(tz)
    # 将来の pandas で fillna(method=...) が非推奨なので obj.ffill/bfill と同義
    out = out.fillna(method="bfill").fillna(method="ffill")
    out = add_time_features(out)
    return out
