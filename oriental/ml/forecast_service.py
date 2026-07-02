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

        history_limit = min(cfg.max_range_limit, 600)
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
                # 今夜のここまでの実測で残り時間の予測をスケール補正（21時半便など）。
                # 経過スロットが無い予測（次の1時間など）では自動的に no-op。
                data = _anchor_to_tonight(df, data, freq_min, self.tz)
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
            # 予期せぬ内部エラーを ok:true（成功）で隠すと、予測グラフが空のまま
            # 5xx もアラートも出ず、障害に何日も気づけない。ok:false で明示する。
            result = {
                "ok": False,
                "error": "forecast_internal_error",
                "detail": str(exc),
                "store": store_id,
                "freq_min": freq_min,
                "data": [],
            }
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
        future_features = self._build_future_features(history, future_times, store_id=store_id)
        men_pred, women_pred = model.predict(future_features)
        total_pred = np.maximum(men_pred, 0) + np.maximum(women_pred, 0)
        men_pred, women_pred, total_pred = self._sparse_store_fallback(
            history, future_times, men_pred, women_pred, total_pred, store_id=store_id
        )
        return [
            {
                "ts": ts.isoformat(),
                "men_pred": float(mp),
                "women_pred": float(wp),
                "total_pred": float(tp),
            }
            for ts, mp, wp, tp in zip(future_times, men_pred, women_pred, total_pred)
        ]

    def _sparse_store_fallback(
        self,
        history: pd.DataFrame,
        future_times: pd.DatetimeIndex,
        men_pred,
        women_pred,
        total_pred,
        *,
        store_id: str,
    ):
        """閑散/疎な店舗向けの縮退予測フォールバック。

        ay_niigata のような客数の少ない店舗では、直近履歴が全体的にゼロに近いと
        LightGBM の主要特徴量（total_slope_30min, same_dow_last_week_total 等）が
        ゼロに潰れ、実際は繁忙な夜もあるのにモデルが 19:00-05:00 の全時間帯で
        ほぼ横ばい・ほぼ0を予測してしまう「モデル崩壊」が起きる。

        このフォールバックは以下の「崩壊シグネチャ」でのみ発火する：
          - 履歴から見てこの店舗は本来賑わうことがある（hist_ceiling >= MIN_ACTIVE）
          - にもかかわらず今回のモデル予測のピークが歴史的上限よりずっと低い
            （pred_peak < COLLAPSE_FRAC * hist_ceiling）
        本当に閑散な店舗（hist_ceiling が低い）や、健全にピークを予測できている
        モデル出力には絶対に介入しない。介入時は、店舗自身の「賑わっていた夜」の
        時間帯別平均カーブ（実測のみ、架空データなし）で置き換える。
        何が起きてもモデル予測を壊さないよう、例外は握りつぶして元の値を返す。
        """
        try:
            if history is None or history.empty:
                return men_pred, women_pred, total_pred
            tot = pd.to_numeric(history["total"], errors="coerce").fillna(0.0)
            # historical activity ceiling: does this store actually get busy?
            hist_ceiling = float(tot.quantile(0.85)) if len(tot) else 0.0
            pred_peak = float(np.max(total_pred)) if len(total_pred) else 0.0
            MIN_ACTIVE = 4.0        # below this the store is genuinely quiet -> leave model alone
            COLLAPSE_FRAC = 0.30    # model predicts < 30% of historical ceiling -> collapsed
            if hist_ceiling < MIN_ACTIVE or pred_peak >= COLLAPSE_FRAC * hist_ceiling:
                return men_pred, women_pred, total_pred   # not degenerate; do nothing

            # Build hour-of-night mean shape from the store's BUSY rows (total>0).
            busy = history.loc[tot > 0].copy()
            if busy.empty:
                return men_pred, women_pred, total_pred
            busy_tot = pd.to_numeric(busy["total"], errors="coerce").fillna(0.0)
            hours = pd.DatetimeIndex(busy["ts"]).hour
            hour_mean = pd.Series(busy_tot.values, index=hours).groupby(level=0).mean()  # {hour: mean total on busy nights}
            overall_busy_mean = float(busy_tot.mean())
            # historical men/women split on busy rows (default 0.5 each)
            m = pd.to_numeric(busy.get("men"), errors="coerce").fillna(0.0).sum()
            w = pd.to_numeric(busy.get("women"), errors="coerce").fillna(0.0).sum()
            male_frac = float(m / (m + w)) if (m + w) > 0 else 0.5

            fut_hours = pd.DatetimeIndex(future_times).hour
            fb_total = np.array([float(hour_mean.get(h, overall_busy_mean)) for h in fut_hours], dtype=float)
            fb_total = np.maximum(fb_total, 0.0)
            fb_men = fb_total * male_frac
            fb_women = fb_total * (1.0 - male_frac)
            self.logger.warning(
                "forecast.service.sparse_fallback store=%s pred_peak=%.2f hist_ceiling=%.2f -> hour-of-night mean shape",
                store_id, pred_peak, hist_ceiling,
            )
            return fb_men, fb_women, fb_total
        except Exception as exc:  # noqa: BLE001 — fallback must never break forecasting
            self.logger.warning("forecast.service.sparse_fallback_skip detail=%s", exc)
            return men_pred, women_pred, total_pred

    def _build_future_features(
        self, history: pd.DataFrame, future_times: pd.DatetimeIndex, *, store_id: str | None = None
    ) -> pd.DataFrame:
        # 呼び出し側 df を破壊しないため（_forecast_generic が同じ df を後続の
        # _anchor_to_tonight / _build_reasoning でも使い回す）、ここでコピーしてから変更する。
        history = history.copy()
        base_cols = ["ts", "men", "women", "total", "weather_code", "temp_c", "precip_mm", "store_id"]
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
                "precip_mm": np.nan,
                "store_id": history["store_id"].iloc[-1] if "store_id" in history.columns and not history.empty else np.nan,
            }
        )
        # 未来行へ実天気「予報」を注入し、天気派生特徴の凍結(train/serve skew)を緩和する。
        # 失敗/座標不明時は weather を NaN のまま残す → preprocess の ffill が働き従来動作＝回帰なし。
        try:
            if store_id:
                from .weather_forecast import get_hourly_forecast

                fc = get_hourly_forecast(store_id, self.tz)
                if fc:
                    hour_keys = pd.DatetimeIndex(future_times).strftime("%Y-%m-%dT%H")
                    wc, tc, pm = [], [], []
                    for key in hour_keys:
                        v = fc.get(key)
                        wc.append(v[0] if v is not None else np.nan)
                        tc.append(v[1] if v is not None else np.nan)
                        pm.append(v[2] if v is not None else np.nan)
                    future_df["weather_code"] = wc
                    future_df["temp_c"] = tc
                    future_df["precip_mm"] = pm
                    self.logger.info(
                        "forecast.service.weather_forecast store=%s filled=%d/%d",
                        store_id,
                        sum(1 for x in wc if x is not None and not (isinstance(x, float) and np.isnan(x))),
                        len(wc),
                    )
        except Exception as exc:  # noqa: BLE001 — 天気予報は best-effort。失敗しても現行動作へ。
            self.logger.warning("forecast.service.weather_forecast_skip store=%s detail=%s", store_id, exc)
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


def _anchor_to_tonight(history, points, freq_min, tz):
    """Nudge the FUTURE portion of tonight's forecast toward how tonight is actually
    going so far — but as a DECAYING blend, not a flat scale.

    Over the already-elapsed slots with real data, compute factor0 = sum(actual) /
    sum(predicted), clamped to [0.5, 2.0]. Then each not-yet-happened slot is scaled by
    an effective factor that starts at factor0 for the next slot and decays toward 1.0
    (the model's own curve) further into the night: eff(h) = 1 + (factor0-1)*decay^h.
    This means a night that merely started early/late corrects the NEAR term without
    over- or under-inflating the late-night PEAK (the model estimates peak magnitude
    better than a short elapsed window) — while a genuinely busy/quiet night still
    lifts/lowers the coming hour. decay is FORECAST_ANCHOR_DECAY (default 0.85 per slot).

    Self-disabling: with no elapsed slots (the next-hour forecast) or fewer than
    MIN_ELAPSED matched slots it returns points unchanged. Toggle off with
    FORECAST_ANCHOR_TONIGHT=0. Leakage-free: only past (<= now) actuals inform the
    correction; only future (> now) slots are adjusted.
    """
    if os.getenv("FORECAST_ANCHOR_TONIGHT", "1").strip() != "1":
        return points
    if not points or history is None or getattr(history, "empty", True):
        return points
    if "total" not in history.columns or "ts" not in history.columns:
        return points

    try:
        now = pd.Timestamp.now(tz=tz)
        freq = f"{max(1, int(freq_min))}min"
        hist = history.dropna(subset=["ts"])
        slots = pd.to_datetime(hist["ts"]).dt.floor(freq)
        actual_by_slot = pd.to_numeric(hist["total"], errors="coerce").groupby(slots).mean().to_dict()
    except Exception:  # noqa: BLE001
        return points

    def _as_ts(value):
        ts = pd.Timestamp(value)
        return ts.tz_localize(tz) if ts.tzinfo is None else ts

    sum_actual = 0.0
    sum_pred = 0.0
    matched = 0
    for p in points:
        ts = _as_ts(p["ts"])
        if ts > now:
            continue
        actual = actual_by_slot.get(ts.floor(freq))
        if actual is None or not np.isfinite(actual):
            continue
        sum_actual += float(actual)
        sum_pred += float(p.get("total_pred", 0.0))
        matched += 1

    MIN_ELAPSED = 3
    if matched < MIN_ELAPSED or sum_pred <= 0.0 or sum_actual <= 0.0:
        return points
    factor0 = max(0.5, min(2.0, sum_actual / sum_pred))
    try:
        decay = float(os.getenv("FORECAST_ANCHOR_DECAY", "0.85"))
    except ValueError:
        decay = 0.85
    decay = min(max(decay, 0.0), 0.999)

    adjusted = []
    horizon = 0  # index among the FUTURE slots (0 = first not-yet-happened slot)
    for p in points:
        ts = _as_ts(p["ts"])
        if ts > now:
            # The correction is strongest right after "now" and decays toward 1.0 (the
            # model's learned curve) further into the night, so a night that merely
            # started early/late bends the near term WITHOUT over-/under-inflating the
            # late-night PEAK (which the model estimates better than a short elapsed window).
            eff = 1.0 + (factor0 - 1.0) * (decay ** horizon)
            horizon += 1
            mp = max(float(p["men_pred"]) * eff, 0.0)
            wp = max(float(p["women_pred"]) * eff, 0.0)
            adjusted.append({
                **p, "men_pred": mp, "women_pred": wp, "total_pred": mp + wp,
                "anchor_factor": round(factor0, 3), "anchor_effective": round(eff, 3),
            })
        else:
            adjusted.append(dict(p))
    return adjusted


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
