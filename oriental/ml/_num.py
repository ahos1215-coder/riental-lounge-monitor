"""数値・時刻・env の小さな共通ヘルパー。

同名の `_is_num` / `_as_ts` / env float 読みが postprocess・forecast_accuracy・
forecast_service に別実装で散っており、特に `_is_num` は「bool を通すか」「NaN を
通すか」の真理値表がモジュールごとに違っていた。意味を1つに決めてここへ集約する。
"""

from __future__ import annotations

import os
from typing import Any

import numpy as np
import pandas as pd


def is_finite_number(v: Any) -> bool:
    """JSON 由来の値が「計算に使える有限の実数」か。

    bool は数値扱いしない（True が 1 として平均に混ざるのを防ぐ）。
    NaN / inf も除外する（合計・平均・除算に混ざると結果全体が NaN になるため）。
    """
    return isinstance(v, (int, float)) and not isinstance(v, bool) and (
        not (isinstance(v, float) and (np.isnan(v) or np.isinf(v)))
    )


def as_ts(value: Any, tz: str) -> pd.Timestamp:
    """任意の時刻表現を指定タイムゾーンの Timestamp にそろえる。

    naive な値はそのタイムゾーンのローカル時刻とみなし（tz_localize）、
    tz 付きの値は同じ瞬間のまま表示タイムゾーンを合わせる（tz_convert）。
    """
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize(tz)
    return ts.tz_convert(tz)


def env_float(name: str, default: float) -> float:
    """env を float で読む。未設定・不正値は default（例外を投げない）。"""
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
