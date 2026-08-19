"""番犬: oriental/ml/_num.py の真理値表・時刻正規化・env 読みを固定する。

`_is_num` は元々 postprocess（bool も NaN も除外）と forecast_accuracy（bool のみ
除外・NaN は通す）で真理値表が違っていた。統一後は「厳しい方（bool も NaN/inf も
除外）」が唯一の意味になる。ここが緩むと精度カードの relative_mae に NaN が混ざる。
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from oriental.ml._num import as_ts, env_float, is_finite_number


@pytest.mark.parametrize(
    "value, expected",
    [
        (1, True),
        (0, True),
        (-3, True),
        (1.5, True),
        (0.0, True),
        (np.float64(2.5), True),
        (True, False),          # bool は数値扱いしない
        (False, False),
        (float("nan"), False),  # NaN は除外（合計・平均が NaN に化けるため）
        (math.inf, False),
        (-math.inf, False),
        (np.nan, False),
        ("1", False),
        (None, False),
        ([1], False),
    ],
)
def test_有限数値の真理値表(value, expected):
    assert is_finite_number(value) is expected


def test_naiveな時刻はローカル時刻として解釈される():
    ts = as_ts("2026-08-19T21:00:00", "Asia/Tokyo")
    assert ts.tzinfo is not None
    assert ts.isoformat() == "2026-08-19T21:00:00+09:00"


def test_tz付きの時刻は同じ瞬間のままJSTへ変換される():
    ts = as_ts("2026-08-19T12:00:00+00:00", "Asia/Tokyo")
    assert ts == pd.Timestamp("2026-08-19T12:00:00+00:00")
    assert ts.isoformat() == "2026-08-19T21:00:00+09:00"


def test_env_floatは未設定と不正値でdefaultを返す(monkeypatch):
    monkeypatch.delenv("MEGRIBI_TEST_FLOAT", raising=False)
    assert env_float("MEGRIBI_TEST_FLOAT", 0.85) == 0.85
    monkeypatch.setenv("MEGRIBI_TEST_FLOAT", "x")
    assert env_float("MEGRIBI_TEST_FLOAT", 0.85) == 0.85
    monkeypatch.setenv("MEGRIBI_TEST_FLOAT", "0.5")
    assert env_float("MEGRIBI_TEST_FLOAT", 0.85) == 0.5
