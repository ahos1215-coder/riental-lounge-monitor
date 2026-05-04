"""Schema v6 (2026-05-03〜) で追加された連休クラスタ特徴量の検証。

`oriental/ml/preprocess.py` の `prepare_dataframe` / `add_time_features` が
`holiday_block_length` と `holiday_block_position` を正しく `FEATURE_COLUMNS` に
反映しているかを確認する。これらは `oriental/ml/holiday_calendar.py` のロジックに
依存しており、特徴量計算の経路でバグが入ると ML 予測精度に直接効くため
回帰検出の最後の砦としてテストを置く。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from oriental.ml.preprocess import FEATURE_COLUMNS, prepare_dataframe


# ---------------------------------------------------------------------------
# FEATURE_COLUMNS 構造の不変条件
# ---------------------------------------------------------------------------


class TestFeatureColumnsShape:
    def test_has_24_features(self) -> None:
        # v5 (22) → v6 (24) のバンプを示す回帰テスト
        assert len(FEATURE_COLUMNS) == 24

    def test_holiday_block_features_present(self) -> None:
        assert "holiday_block_length" in FEATURE_COLUMNS
        assert "holiday_block_position" in FEATURE_COLUMNS

    def test_v5_features_preserved(self) -> None:
        # v5 から v6 で削除された特徴量がないことを確認
        v5_required = [
            "month",
            "hour",
            "minute",
            "day_of_week",
            "is_weekend",
            "is_holiday",
            "is_pre_holiday",
            "holiday_pos",
            "is_rainy",
            "precip_mm",
            "same_dow_last_week_total",
            "total_slope_30min",
            "extreme_weather",
        ]
        for col in v5_required:
            assert col in FEATURE_COLUMNS, f"v5 feature {col} dropped"


# ---------------------------------------------------------------------------
# DataFrame 出力に v6 特徴量が含まれるか
# ---------------------------------------------------------------------------


JST = timezone(timedelta(hours=9))


def _records_for_date(target_date: datetime, count: int = 4) -> list[dict]:
    """指定 JST 日付の 19:00 から 15 分間隔で count 件のスクレイプ記録を生成する。

    入力 `target_date` は JST 日付として解釈される (tz 無し / UTC は内部で JST に揃える)。
    holiday_block 計算は JST date 単位で行われるため、テスト入力もそれに合わせる。
    """
    if target_date.tzinfo is None:
        target_date = target_date.replace(tzinfo=JST)
    else:
        target_date = target_date.astimezone(JST)
    base = target_date.replace(hour=19, minute=0, second=0, microsecond=0)
    out: list[dict] = []
    for i in range(count):
        ts = base + timedelta(minutes=15 * i)
        out.append(
            {
                # JST tz-aware ISO 8601 (e.g. "2026-05-04T19:00:00+09:00") を渡す
                "ts": ts.isoformat(),
                "men": 5 + i,
                "women": 8 + i,
                "total": 13 + 2 * i,
                "store_id": "ol_shibuya",
                "weather_code": 1,
                "temp_c": 20.0,
                "precip_mm": 0.0,
            }
        )
    return out


class TestPrepareDataframeV6:
    def test_output_includes_holiday_block_columns(self) -> None:
        records = _records_for_date(datetime(2026, 4, 7, tzinfo=timezone.utc))  # 平日 (火)
        df = prepare_dataframe(records, "Asia/Tokyo")
        assert "holiday_block_length" in df.columns
        assert "holiday_block_position" in df.columns

    def test_weekday_has_zero_block_length(self) -> None:
        # 2026-04-07 (火) JST は完全に平日
        records = _records_for_date(datetime(2026, 4, 7, tzinfo=timezone.utc))
        df = prepare_dataframe(records, "Asia/Tokyo")
        # 19:00 JST = 10:00 UTC、すべて平日扱い
        assert (df["holiday_block_length"] == 0).all()

    def test_isolated_holiday_has_length_one(self) -> None:
        # 2026-11-03 (火・文化の日) は前後平日の単発祝日
        records = _records_for_date(datetime(2026, 11, 3, tzinfo=timezone.utc))
        df = prepare_dataframe(records, "Asia/Tokyo")
        assert (df["holiday_block_length"] == 1).all()
        # 単発の場合 position は 0.5 (中立値)
        assert (df["holiday_block_position"] == 0.5).all()

    def test_gw_block_recognized_as_5_days(self) -> None:
        # 2026-05-04 (月・みどりの日) は GW 5 連休 (5/2-5/6) の中日
        records = _records_for_date(datetime(2026, 5, 4, tzinfo=timezone.utc))
        df = prepare_dataframe(records, "Asia/Tokyo")
        assert (df["holiday_block_length"] == 5).all()
        # 5/2(土,0) 5/3(日,0.25) 5/4(月,0.5) 5/5(火,0.75) 5/6(水,1.0)
        assert df["holiday_block_position"].iloc[0] == pytest.approx(0.5, abs=0.01)

    def test_year_end_block_recognized(self) -> None:
        # 2025-12-30 (火) は年末年始連休 (12/27土 〜 1/4日 = 9 日) の途中
        records = _records_for_date(datetime(2025, 12, 30, tzinfo=timezone.utc))
        df = prepare_dataframe(records, "Asia/Tokyo")
        assert (df["holiday_block_length"] == 9).all()

    def test_weekend_has_length_two(self) -> None:
        # 2026-04-11 (土) は通常週末 (土+日 で length=2)
        records = _records_for_date(datetime(2026, 4, 11, tzinfo=timezone.utc))
        df = prepare_dataframe(records, "Asia/Tokyo")
        assert (df["holiday_block_length"] == 2).all()


# ---------------------------------------------------------------------------
# 重複日付に対する集計効率 (デグレ検出)
# ---------------------------------------------------------------------------


class TestPrepareDataframeUniqueDateOptimization:
    def test_same_date_rows_share_same_block_value(self) -> None:
        """同じ JST 日付の行は ALL `holiday_block_length` が同値になるべき。

        v6 の実装は `unique_dates` ループで dict 化する最適化を含む。
        ループバグで隣接行の値が混じると ML 推論にゆっくり効く形でバグるので
        最低限の不変条件として確認する。
        """
        # 同日内で 30 分分の 6 サンプル
        records = _records_for_date(datetime(2026, 5, 4, tzinfo=timezone.utc), count=6)
        df = prepare_dataframe(records, "Asia/Tokyo")
        assert df["holiday_block_length"].nunique() == 1
        assert df["holiday_block_position"].nunique() == 1


# ---------------------------------------------------------------------------
# v6 特徴量がなくても古いコードが落ちないか (back-compat 安全弁)
# ---------------------------------------------------------------------------


class TestFeatureColumnsAccessibility:
    def test_holiday_block_columns_are_filled_to_int_or_float(self) -> None:
        records = _records_for_date(datetime(2026, 5, 4, tzinfo=timezone.utc))
        df = prepare_dataframe(records, "Asia/Tokyo")
        # holiday_block_length は int、position は float (中立値 0.5 含む)
        assert pd.api.types.is_integer_dtype(df["holiday_block_length"])
        assert pd.api.types.is_float_dtype(df["holiday_block_position"])
