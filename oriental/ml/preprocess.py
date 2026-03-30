from __future__ import annotations

from datetime import date, timedelta

import jpholiday
import numpy as np
import pandas as pd

FEATURE_COLUMNS = [
    "month",
    "hour",
    "minute",
    "minutes_to_midnight",
    "day_of_week",
    # "dow" removed: identical to day_of_week (both dt.dayofweek)
    "is_weekend",
    "is_holiday",
    "is_pre_holiday",
    "holiday_pos",
    "days_from_25th",
    "is_rainy",
    "precip_mm",
    "next_morning_rain",
    "temp_diff_yesterday",
    # "gender_diff" removed: NaN at inference time (men/women unknown for future rows)
    "feat_payday_night_peak",
    "feat_rain_night_exit",
    "feat_pre_holiday_surge",
    "sin_time",
    "cos_time",
    # Lag/MA features removed: NaN at inference time → median-filled → constant noise
    # "men_lag_12", "men_lag_24", "men_ma_2", "men_ma_4",
    # "women_lag_12", "women_lag_24", "women_ma_2", "women_ma_4",
    # v3: 同曜日先週の実測値（推論時にも利用可能 — 7日分の履歴から算出）
    "same_dow_last_week_total",
    # v4: 直近30分の人数変化速度（6行分の差分）。推論時は history の末尾から算出
    "total_slope_30min",
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
    if "weather_code" not in df.columns:
        df["weather_code"] = np.nan
    if "temp_c" not in df.columns:
        df["temp_c"] = np.nan
    if "precip_mm" not in df.columns:
        df["precip_mm"] = np.nan
    df["weather_code"] = pd.to_numeric(df["weather_code"], errors="coerce")
    df["temp_c"] = pd.to_numeric(df["temp_c"], errors="coerce")
    df["precip_mm"] = pd.to_numeric(df["precip_mm"], errors="coerce")

    # 1時間おき取得の天候値を5分粒度へ引き継ぐ（店舗単位）
    weather_cols = ["weather_code", "temp_c", "precip_mm"]
    if "store_id" in df.columns:
        df[weather_cols] = df.groupby("store_id", dropna=False)[weather_cols].ffill()
    else:
        df[weather_cols] = df[weather_cols].ffill()
    return add_time_features(df)


def add_time_features(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    group_keys = ["store_id"] if "store_id" in df.columns else []
    ts_local = pd.to_datetime(df["ts"], errors="coerce")
    row_dates = ts_local.dt.date

    df["month"] = ts_local.dt.month
    df["hour"] = df["ts"].dt.hour
    df["minute"] = df["ts"].dt.minute
    df["day_of_week"] = df["ts"].dt.dayofweek
    df["dow"] = df["ts"].dt.dayofweek
    df["is_weekend"] = df["dow"].isin([4, 5]).astype(int)
    # 休日は「日曜 or 祝日当日」で定義
    is_sunday = df["dow"] == 6
    is_jp_holiday = row_dates.map(lambda d: 1 if jpholiday.is_holiday(d) else 0).astype(int)
    df["is_holiday"] = (is_sunday | (is_jp_holiday == 1)).astype(int)
    tomorrow = row_dates.map(lambda d: d + timedelta(days=1))
    is_tomorrow_holiday = tomorrow.map(lambda d: 1 if jpholiday.is_holiday(d) else 0).astype(int)
    # 祝前日は「金曜 or 土曜 or 翌日が祝日」で定義
    df["is_pre_holiday"] = ((df["dow"].isin([4, 5])) | (is_tomorrow_holiday == 1)).astype(int)

    holiday_like_dates = pd.DataFrame({"date": row_dates, "flag": (df["is_holiday"] == 1) | (df["is_weekend"] == 1)})
    holiday_like_dates = holiday_like_dates.drop_duplicates(subset=["date"]).sort_values("date")
    pos_map = _holiday_position_map(holiday_like_dates["date"].tolist(), holiday_like_dates["flag"].tolist())
    df["holiday_pos"] = row_dates.map(lambda d: pos_map.get(d, 0)).astype(int)

    df["days_from_25th"] = row_dates.map(_days_from_25th_clipped).astype(float)
    df["is_rainy"] = (df["weather_code"].fillna(-1) >= 51).astype(int)
    df["precip_mm"] = pd.to_numeric(df["precip_mm"], errors="coerce").fillna(0.0).astype(float)

    # 翌朝（06:00-09:59）の降雨予報/実測が1件でもあればフラグ化
    if group_keys:
        rain_map = (
            df.assign(date_key=row_dates, rainy=(df["weather_code"].fillna(-1) >= 51))
            .loc[(df["hour"] >= 6) & (df["hour"] <= 9)]
            .groupby(group_keys + ["date_key"], dropna=False)["rainy"]
            .max()
            .rename("has_rain")
            .reset_index()
        )
        df["date_key"] = tomorrow
        df = df.merge(rain_map, on=group_keys + ["date_key"], how="left")
        df["next_morning_rain"] = pd.to_numeric(df["has_rain"], errors="coerce").fillna(0).clip(0, 1).astype(int)
        df = df.drop(columns=["has_rain", "date_key"])
    else:
        rain_map_simple = (
            df.assign(date_key=row_dates, rainy=(df["weather_code"].fillna(-1) >= 51))
            .loc[(df["hour"] >= 6) & (df["hour"] <= 9)]
            .groupby("date_key")["rainy"]
            .max()
            .to_dict()
        )
        df["next_morning_rain"] = tomorrow.map(lambda d: 1 if rain_map_simple.get(d, False) else 0).astype(int)

    # 同時刻の前日比（店舗ごと）
    temp_ref = df.copy()
    temp_ref["date_key"] = row_dates
    temp_ref = temp_ref[group_keys + ["date_key", "hour", "minute", "temp_c"]].rename(columns={"temp_c": "temp_prev"})
    current_temp = df.copy()
    current_temp["date_key"] = row_dates.map(lambda d: d - timedelta(days=1))
    merge_cols = group_keys + ["date_key", "hour", "minute"]
    merged = current_temp.merge(temp_ref, on=merge_cols, how="left")
    df["temp_diff_yesterday"] = (df["temp_c"] - merged["temp_prev"]).astype(float)

    if group_keys:
        grouped = df.groupby(group_keys, dropna=False)
        df["men_lag_12"] = grouped["men"].shift(12)
        df["men_lag_24"] = grouped["men"].shift(24)
        df["women_lag_12"] = grouped["women"].shift(12)
        df["women_lag_24"] = grouped["women"].shift(24)
        df["men_ma_2"] = grouped["men"].transform(lambda s: s.rolling(2, min_periods=1).mean())
        df["men_ma_4"] = grouped["men"].transform(lambda s: s.rolling(4, min_periods=1).mean())
        df["women_ma_2"] = grouped["women"].transform(lambda s: s.rolling(2, min_periods=1).mean())
        df["women_ma_4"] = grouped["women"].transform(lambda s: s.rolling(4, min_periods=1).mean())
    else:
        df["men_lag_12"] = df["men"].shift(12)
        df["men_lag_24"] = df["men"].shift(24)
        df["women_lag_12"] = df["women"].shift(12)
        df["women_lag_24"] = df["women"].shift(24)
        df["men_ma_2"] = df["men"].rolling(2, min_periods=1).mean()
        df["men_ma_4"] = df["men"].rolling(4, min_periods=1).mean()
        df["women_ma_2"] = df["women"].rolling(2, min_periods=1).mean()
        df["women_ma_4"] = df["women"].rolling(4, min_periods=1).mean()

    # --- 同曜日先週の実測 total（v3 feature） ---
    # 各行の ts を15分単位に丸め、7日前の同スロットの total を参照する。
    # 学習時: DataFrame 内の過去データから自動算出。
    # 推論時: 7日分の history が concat されているため future 行でも算出可能。
    # マッチしなければ NaN — XGBoost は NaN を native に処理する。
    _ts_rounded = ts_local.dt.floor("15min").dt.tz_localize(None)
    _valid_mask = df["total"].notna()
    _lookup_df = pd.DataFrame({
        "_future_ts": (_ts_rounded[_valid_mask] + pd.Timedelta(days=7)).reset_index(drop=True),
        "_total": df.loc[_valid_mask, "total"].reset_index(drop=True),
    })
    if group_keys:
        for gk in group_keys:
            _lookup_df[gk] = df.loc[_valid_mask, gk].reset_index(drop=True)
        _lookup_df = _lookup_df.groupby(group_keys + ["_future_ts"], dropna=False).agg({"_total": "mean"}).reset_index()
        _merge_df = pd.DataFrame({"_future_ts": _ts_rounded.reset_index(drop=True)})
        for gk in group_keys:
            _merge_df[gk] = df[gk].reset_index(drop=True)
        _merged = _merge_df.merge(_lookup_df, on=group_keys + ["_future_ts"], how="left")
    else:
        _lookup_df = _lookup_df.groupby("_future_ts", dropna=False).agg({"_total": "mean"}).reset_index()
        _merge_df = pd.DataFrame({"_future_ts": _ts_rounded.reset_index(drop=True)})
        _merged = _merge_df.merge(_lookup_df, on="_future_ts", how="left")
    df["same_dow_last_week_total"] = _merged["_total"].values

    # --- 直近30分の人数変化速度（v4 feature） ---
    # 5分間隔のデータで6行前との差 = 30分間の変化量。
    # 学習時: 連続データから自動算出。推論時: history の末尾から future の先頭行に引き継がれる。
    if group_keys:
        df["total_slope_30min"] = df.groupby(group_keys, dropna=False)["total"].diff(6)
    else:
        df["total_slope_30min"] = df["total"].diff(6)

    df["gender_diff"] = (df["men"] - df["women"]).astype(float)
    df["minutes_to_midnight"] = (24 * 60 - (df["hour"] * 60 + df["minute"])).astype(float)
    df["feat_payday_night_peak"] = (
        (df["days_from_25th"] >= -1)
        & (df["days_from_25th"] <= 2)
        & (df["dow"].isin([4, 5]))
        & (df["hour"].isin([21, 22, 23, 0]))
    ).astype(int)
    df["feat_rain_night_exit"] = ((df["is_rainy"] == 1) & (df["hour"] >= 22)).astype(int)
    df["feat_pre_holiday_surge"] = (
        (df["is_pre_holiday"] == 1) & (df["hour"] >= 20) & (df["hour"] <= 23)
    ).astype(int)
    minutes = df["hour"] * 60 + df["minute"]
    df["sin_time"] = np.sin(2 * np.pi * minutes / 1440)
    df["cos_time"] = np.cos(2 * np.pi * minutes / 1440)

    numeric_cols = [c for c in FEATURE_COLUMNS if c in df.columns]
    for col in numeric_cols:
        median_val = pd.to_numeric(df[col], errors="coerce").median()
        fill_val = float(median_val) if not np.isnan(median_val) else 0.0
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(fill_val)

    for col in FEATURE_COLUMNS:
        if col not in df.columns:
            df[col] = 0.0

    df = df.bfill().ffill()
    return df


def _holiday_position_map(dates: list[date], flags: list[bool]) -> dict[date, int]:
    result: dict[date, int] = {}
    if not dates:
        return result
    i = 0
    n = len(dates)
    while i < n:
        if not flags[i]:
            result[dates[i]] = 0
            i += 1
            continue
        j = i
        while j + 1 < n and flags[j + 1] and (dates[j + 1] - dates[j]).days == 1:
            j += 1
        if i == j:
            result[dates[i]] = 0
        else:
            for k in range(i, j + 1):
                if k == i:
                    result[dates[k]] = 1
                elif k == j:
                    result[dates[k]] = 3
                else:
                    result[dates[k]] = 2
        i = j + 1
    return result


def _is_payday_week(d: date) -> int:
    return int(_in_payday_window_for_month(d, d.year, d.month) or _in_prev_month_window(d))


def _days_from_25th_clipped(d: date) -> int:
    # 日付の周期性を保ちつつ、25日付近(-5..+5)を強調する連続特徴量
    diff = d.day - 25
    return int(max(-5, min(5, diff)))


def _in_prev_month_window(d: date) -> bool:
    if d.month == 1:
        y, m = d.year - 1, 12
    else:
        y, m = d.year, d.month - 1
    return _in_payday_window_for_month(d, y, m)


def _in_payday_window_for_month(d: date, year: int, month: int) -> bool:
    try:
        payday = date(year, month, 25)
    except ValueError:
        return False
    # 25日から直後の日曜日まで
    days_to_sunday = (6 - payday.weekday()) % 7
    window_end = payday + timedelta(days=days_to_sunday)
    return payday <= d <= window_end


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
    out = out.bfill().ffill()
    out = add_time_features(out)
    return out
