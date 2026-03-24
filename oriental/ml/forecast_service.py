from __future__ import annotations

import os
from typing import Callable, Dict

import numpy as np
import pandas as pd

from ..data.provider import GoogleSheetProvider, SupabaseError, SupabaseLogsProvider
from .model_registry import ModelRegistryError, ModelSchemaMismatchError
from .preprocess import FEATURE_COLUMNS, add_time_features, prepare_dataframe

FutureBuilder = Callable[[pd.DataFrame], pd.DatetimeIndex]


class ForecastService:
    """Facade that orchestrates provider -> preprocessing -> prediction pipelines."""

    def __init__(
        self,
        provider,
        timezone: str,
        *,
        history_days: int = 7,
        history_limit: int | None = None,
        fallback_provider=None,
        model_registry=None,
        backend: str = "legacy",
    ):
        self.provider = provider
        self.timezone = timezone
        self.tz = timezone
        self.logger = provider.logger
        self.history_days = history_days
        self.history_limit = history_limit
        self.fallback_provider = fallback_provider
        self.model_registry = model_registry
        self.backend = backend

    @classmethod
    def from_app(cls, app):
        cfg = app.config["APP_CONFIG"]
        from .model_registry import ForecastModelRegistry

        legacy_provider = GoogleSheetProvider(cfg.gs_read_url, cfg.data_file, logger=app.logger)

        backend = (cfg.data_backend or "legacy").lower()
        provider = legacy_provider
        fallback_provider = None

        if backend == "supabase" and cfg.supabase_url and cfg.supabase_service_role_key:
            provider = SupabaseLogsProvider(
                base_url=cfg.supabase_url,
                api_key=cfg.supabase_service_role_key,
                session=None,  # use clean session to avoid accidental non-ASCII headers
                logger=app.logger,
            )
            fallback_provider = legacy_provider

        history_limit = min(cfg.max_range_limit, 2000)
        model_registry = ForecastModelRegistry.from_app(app)

        return cls(
            provider=provider,
            timezone=cfg.timezone,
            history_days=7,
            history_limit=history_limit,
            fallback_provider=fallback_provider,
            model_registry=model_registry,
            backend=backend,
        )

    def forecast_next_hour(self, store_id: str, freq_min: int) -> dict:
        """Return predictions for the next hour at freq_min cadence."""
        periods = max(1, 60 // freq_min)

        def builder(history: pd.DataFrame) -> pd.DatetimeIndex:
            ref = history["ts"].iloc[-1] if not history.empty else None
            return _future_range(ref, freq_min, periods, self.tz)

        return self._forecast_generic(store_id, freq_min, builder)

    def forecast_today(self, store_id: str, freq_min: int, *, start_h: int = 19, end_h: int = 5) -> dict:
        """Return 19:00-05:00 slots for the specified store."""

        def builder(_history: pd.DataFrame) -> pd.DatetimeIndex:
            now = pd.Timestamp.now(tz=self.tz)
            start = now.replace(hour=start_h, minute=0, second=0, microsecond=0)
            if now.hour < start_h:
                start -= pd.Timedelta(days=1)
            end = (start + pd.Timedelta(days=1)).replace(hour=end_h, minute=0, second=0, microsecond=0)
            return pd.date_range(start=start, end=end, freq=f"{freq_min}min", inclusive="left", tz=self.tz)

        return self._forecast_generic(
            store_id,
            freq_min,
            builder,
            extra_meta={"start_h": start_h, "end_h": end_h},
        )

    def _forecast_generic(
        self,
        store_id: str,
        freq_min: int,
        future_builder: FutureBuilder,
        extra_meta: Dict[str, int] | None = None,
    ) -> dict:
        try:
            records = self._fetch_history(store_id)
            df = prepare_dataframe(records, self.timezone)
            self.logger.info("forecast.service.history size=%d", len(df))

            future_times = future_builder(df)
            self.logger.info("forecast.service.future size=%d", len(future_times))

            if df.empty:
                data = _zero_payload(future_times)
                reasoning = {"signals": {}, "notes": ["履歴データ不足のため根拠情報なし"]}
            else:
                data = self._predict_with_history(df, future_times, store_id=store_id)
                reasoning = self._build_reasoning(df, store_id=store_id)
            self.logger.info("forecast.service.predicted size=%d", len(data))

            result = {"ok": True, "store": store_id, "freq_min": freq_min, "data": data, "reasoning": reasoning}
            if extra_meta:
                result.update(extra_meta)
            return result
        except SupabaseError as exc:
            self.logger.error("forecast.service.supabase_error store=%s", store_id, exc_info=exc)
            result = {"ok": False, "error": "supabase_error", "detail": str(exc), "store": store_id, "freq_min": freq_min, "data": []}
            if extra_meta:
                result.update(extra_meta)
            return result
        except ModelSchemaMismatchError as exc:
            self.logger.error("forecast.service.model_schema_mismatch store=%s", store_id, exc_info=exc)
            result = {"ok": False, "error": "model_schema_mismatch", "detail": str(exc), "store": store_id, "freq_min": freq_min, "data": []}
            if extra_meta:
                result.update(extra_meta)
            return result
        except ModelRegistryError as exc:
            self.logger.error("forecast.service.model_unavailable store=%s", store_id, exc_info=exc)
            result = {"ok": False, "error": "model_unavailable", "detail": str(exc), "store": store_id, "freq_min": freq_min, "data": []}
            if extra_meta:
                result.update(extra_meta)
            return result
        except Exception as exc:  # noqa: BLE001
            self.logger.error("forecast.service.error store=%s", store_id, exc_info=exc)
            result = {"ok": True, "store": store_id, "freq_min": freq_min, "data": []}
            if extra_meta:
                result.update(extra_meta)
            return result

    def _fetch_history(self, store_id: str) -> list[dict]:
        try:
            return self.provider.get_records(store_id, days=self.history_days, limit=self.history_limit)
        except SupabaseError:
            if self.backend == "supabase" and self.fallback_provider:
                self.logger.warning("forecast.service.supabase_fallback store=%s", store_id)
                return self.fallback_provider.get_records(store_id)
            raise

    def _predict_with_history(self, history: pd.DataFrame, future_times: pd.DatetimeIndex, *, store_id: str) -> list[dict]:
        if self.model_registry is None:
            raise ModelRegistryError("model_registry is not configured")
        bundle = self.model_registry.get_bundle(store_id=store_id)
        model = bundle.model
        future_features = self._build_future_features(history, future_times)
        men_pred, women_pred = model.predict(future_features)
        total_pred = np.maximum(men_pred, 0) + np.maximum(women_pred, 0)
        return [
            {
                "ts": ts.isoformat(),
                "men_pred": float(mp),
                "women_pred": float(wp),
                "total_pred": float(tp),
            }
            for ts, mp, wp, tp in zip(future_times, men_pred, women_pred, total_pred)
        ]

    def _build_future_features(self, history: pd.DataFrame, future_times: pd.DatetimeIndex) -> pd.DataFrame:
        base_cols = ["ts", "men", "women", "total", "weather_code", "temp_c", "store_id"]
        for col in base_cols:
            if col not in history.columns:
                history[col] = np.nan
        hist_base = history[base_cols]
        future_df = pd.DataFrame(
            {
                "ts": pd.DatetimeIndex(future_times, tz=self.tz),
                "men": np.nan,
                "women": np.nan,
                "total": np.nan,
                "weather_code": np.nan,
                "temp_c": np.nan,
                "store_id": history["store_id"].iloc[-1] if "store_id" in history.columns and not history.empty else np.nan,
            }
        )
        combined = pd.concat([hist_base, future_df], ignore_index=True)
        combined = add_time_features(combined)
        return combined.tail(len(future_times))[FEATURE_COLUMNS]

    def _build_reasoning(self, history: pd.DataFrame, *, store_id: str) -> dict:
        latest = history.iloc[-1]
        signals = {
            "is_rainy": _to_int(latest.get("is_rainy")),
            "is_pre_holiday": _to_int(latest.get("is_pre_holiday")),
            "is_holiday": _to_int(latest.get("is_holiday")),
            "days_from_25th": _to_float(latest.get("days_from_25th")),
            "minutes_to_midnight": _to_float(latest.get("minutes_to_midnight")),
            "precip_mm": _to_float(latest.get("precip_mm")),
            "feat_payday_night_peak": _to_int(latest.get("feat_payday_night_peak")),
            "feat_rain_night_exit": _to_int(latest.get("feat_rain_night_exit")),
            "feat_pre_holiday_surge": _to_int(latest.get("feat_pre_holiday_surge")),
        }
        notes: list[str] = []

        if signals["is_rainy"] == 1:
            rain_weight = os.getenv("ML_TRAIN_WEIGHT_RAIN", "1.8")
            notes.append(f"{store_id}：雨天重み付け（{rain_weight}x）適用中")
        if signals["feat_payday_night_peak"] == 1:
            notes.append(f"{store_id}：給料日ピーク補正あり")
        if signals["feat_rain_night_exit"] == 1:
            notes.append("雨天×深夜帯の離脱シグナル条件")
        if signals["feat_pre_holiday_surge"] == 1:
            notes.append("祝前日サージ条件")
        if not notes:
            notes.append("通常条件で推論")

        return {"signals": signals, "notes": notes}


def _future_range(start_dt, freq_min: int, periods: int, tz: str):
    ref = pd.Timestamp(start_dt) if start_dt is not None else pd.Timestamp.now(tz=tz)
    if ref.tzinfo is None:
        ref = ref.tz_localize(tz)
    else:
        ref = ref.tz_convert(tz)
    start = ref + pd.Timedelta(minutes=freq_min)
    return pd.date_range(start=start, periods=periods, freq=f"{freq_min}min", tz=tz)


def _zero_payload(future_times):
    return [
        {"ts": ts.isoformat(), "men_pred": 0.0, "women_pred": 0.0, "total_pred": 0.0}
        for ts in future_times
    ]


def _to_int(v) -> int:
    try:
        return int(float(v))
    except Exception:  # noqa: BLE001
        return 0


def _to_float(v) -> float | None:
    try:
        return float(v)
    except Exception:  # noqa: BLE001
        return None
