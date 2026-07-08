"""ForecastService の新規追加パスの単体テスト (lightgbm 非依存)。

model_registry=None で ForecastService を直接組み立て、以下2つのヘルパーを
モデル呼び出しを経由せず直接テストする:

  - _sparse_store_fallback: 閑散/疎な店舗向けの「モデル崩壊」検知・置換ロジック
  - _build_future_features: 未来行への実天気予報注入 (weather_forecast.get_hourly_forecast)
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
import pytest

from oriental.ml import weather_forecast as weather_forecast_module
from oriental.ml.forecast_service import ForecastService
from oriental.ml.preprocess import FEATURE_COLUMNS, prepare_dataframe

TZ = "Asia/Tokyo"


class _FakeProvider:
    logger = logging.getLogger("test")


def make_svc() -> ForecastService:
    return ForecastService(provider=_FakeProvider(), timezone=TZ, model_registry=None)


def _future_times(n: int = 8) -> pd.DatetimeIndex:
    return pd.date_range("2026-07-03 19:00", periods=n, freq="60min", tz=TZ)


def _busy_history() -> pd.DataFrame:
    """hours 19-23 にわたり total 10..30 程度の「賑わっている」履歴を約40行作る。
    men/women はおよそ 55/45 split。"""
    rows = []
    hours = [19, 20, 21, 22, 23]
    totals_by_hour = {19: 10, 20: 18, 21: 25, 22: 30, 23: 22}
    day0 = pd.Timestamp("2026-06-20", tz=TZ)
    for day_offset in range(8):
        day = day0 + pd.Timedelta(days=day_offset)
        for h in hours:
            base_total = totals_by_hour[h]
            # give a little spread so quantile(0.85) reflects the busy ceiling, not a
            # single constant
            total = base_total + (day_offset % 3)
            men = round(total * 0.55)
            women = total - men
            rows.append(
                {
                    "ts": day.replace(hour=h, minute=0, second=0, microsecond=0),
                    "men": men,
                    "women": women,
                    "total": total,
                }
            )
    return pd.DataFrame(rows)


def _quiet_history() -> pd.DataFrame:
    """全てのtotalが0か1の「本当に閑散」な店舗の履歴。"""
    rows = []
    day0 = pd.Timestamp("2026-06-20", tz=TZ)
    for day_offset in range(8):
        day = day0 + pd.Timedelta(days=day_offset)
        for h in (19, 20, 21, 22, 23):
            total = 1 if (day_offset + h) % 4 == 0 else 0
            rows.append(
                {
                    "ts": day.replace(hour=h, minute=0, second=0, microsecond=0),
                    "men": total,
                    "women": 0,
                    "total": total,
                }
            )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# _sparse_store_fallback
# ---------------------------------------------------------------------------


class TestSparseStoreFallback:
    def test_collapse_triggers_fallback_with_busy_history(self):
        svc = make_svc()
        history = _busy_history()
        future_times = _future_times(8)
        # model predicts near-zero across the board despite historically busy nights
        total_pred = np.full(8, 0.02)
        men_pred = np.full(8, 0.01)
        women_pred = np.full(8, 0.01)

        men_out, women_out, total_out = svc._sparse_store_fallback(
            history, future_times, men_pred, women_pred, total_pred, store_id="ay_yokohama"
        )

        pred_peak = float(np.max(total_pred))
        assert float(np.max(total_out)) > 1.0
        assert float(np.max(total_out)) > pred_peak
        # fallback should not just be a copy of the flat prediction
        assert not np.allclose(total_out, total_pred)
        assert np.allclose(men_out + women_out, total_out)

    def test_healthy_model_output_left_unchanged(self):
        svc = make_svc()
        history = _busy_history()
        future_times = _future_times(8)
        # model predicts a real peak comparable to the historical ceiling -> no collapse
        total_pred = np.array([2.0, 5.0, 10.0, 15.0, 20.0, 18.0, 8.0, 3.0])
        men_pred = total_pred * 0.55
        women_pred = total_pred * 0.45

        men_out, women_out, total_out = svc._sparse_store_fallback(
            history, future_times, men_pred, women_pred, total_pred, store_id="ol_shibuya"
        )

        assert np.array_equal(total_out, total_pred)
        assert np.array_equal(men_out, men_pred)
        assert np.array_equal(women_out, women_pred)

    def test_genuinely_quiet_store_left_unchanged(self):
        svc = make_svc()
        history = _quiet_history()
        future_times = _future_times(8)
        total_pred = np.full(8, 0.02)
        men_pred = np.full(8, 0.01)
        women_pred = np.full(8, 0.01)

        men_out, women_out, total_out = svc._sparse_store_fallback(
            history, future_times, men_pred, women_pred, total_pred, store_id="ol_quiet"
        )

        assert np.array_equal(total_out, total_pred)
        assert np.array_equal(men_out, men_pred)
        assert np.array_equal(women_out, women_pred)

    @pytest.mark.parametrize("history", [pd.DataFrame(), None])
    def test_empty_or_none_history_returns_inputs_unchanged(self, history):
        svc = make_svc()
        future_times = _future_times(8)
        total_pred = np.full(8, 0.02)
        men_pred = np.full(8, 0.01)
        women_pred = np.full(8, 0.01)

        men_out, women_out, total_out = svc._sparse_store_fallback(
            history, future_times, men_pred, women_pred, total_pred, store_id="ol_empty"
        )

        assert np.array_equal(total_out, total_pred)
        assert np.array_equal(men_out, men_pred)
        assert np.array_equal(women_out, women_pred)


# ---------------------------------------------------------------------------
# _build_future_features weather injection
# ---------------------------------------------------------------------------


def _weather_history_records() -> list[dict]:
    base = pd.Timestamp("2026-07-02 19:00", tz=TZ)
    records = []
    for i in range(8):
        ts = base + pd.Timedelta(minutes=15 * i)
        records.append(
            {
                "ts": ts.isoformat(),
                "men": 5 + i,
                "women": 4 + i,
                "total": 9 + 2 * i,
                "store_id": "ol_shibuya",
                "weather_code": 1,
                "temp_c": 25.0,
                "precip_mm": 0.0,
            }
        )
    return records


class TestBuildFutureFeaturesWeatherInjection:
    def test_injected_forecast_reflected_in_output(self, monkeypatch):
        svc = make_svc()
        history = prepare_dataframe(_weather_history_records(), TZ)
        future_times = _future_times(4)

        hour_keys = pd.DatetimeIndex(future_times).strftime("%Y-%m-%dT%H")
        fake_forecast = {
            key: (61, 30.0 + i, 2.5) for i, key in enumerate(hour_keys)
        }

        def _fake_get_hourly_forecast(store_id, tz):
            assert store_id == "ol_shibuya"
            return fake_forecast

        monkeypatch.setattr(
            weather_forecast_module, "get_hourly_forecast", _fake_get_hourly_forecast
        )

        result = svc._build_future_features(history, future_times, store_id="ol_shibuya")

        assert len(result) == len(future_times)
        assert list(result.columns) == FEATURE_COLUMNS
        # is_rainy is derived from weather_code >= 51; injected code is 61 (rain) for
        # every future hour, so all future rows should be flagged rainy.
        assert (result["is_rainy"] == 1).all()
        # precip_mm should reflect the injected forecast value, not an ffilled 0.0 from
        # the (dry) history tail.
        assert (result["precip_mm"] == 2.5).all()

    def test_missing_forecast_falls_back_to_ffill_without_crash(self, monkeypatch):
        svc = make_svc()
        history = prepare_dataframe(_weather_history_records(), TZ)
        future_times = _future_times(4)

        def _empty_forecast(store_id, tz):
            return {}

        monkeypatch.setattr(
            weather_forecast_module, "get_hourly_forecast", _empty_forecast
        )

        result = svc._build_future_features(history, future_times, store_id="ol_shibuya")

        assert len(result) == len(future_times)
        assert list(result.columns) == FEATURE_COLUMNS
        assert not result.isna().any().any()
