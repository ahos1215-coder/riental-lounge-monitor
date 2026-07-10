"""夜タイプ分類 (oriental/ml/night_type.py) のテスト。純関数・ネットワーク無し。

期待値の根拠（すべて 2026 年の実カレンダーで検証、jpholiday==1.0.3）:
- classify_night は「明日休み→H / 今日休み→M / 平日通常→L」の 2 ビット規則。
  day_off は土日 or 法定祝日のみ（慣習休業は含めない）。
- special_block は obon(8/13-15) / nye(12/29-1/3) / gw(4/29-5/6 を含む連休)。
- night_date_of は -6h シフト（00:00-05:59 は前夜）。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from oriental.ml.night_type import (
    classify_night,
    day_off,
    night_date_of,
    special_block,
)

JST = timezone(timedelta(hours=9))


class TestClassifyNight:
    def test_friday_is_high(self) -> None:
        # 2026-04-10 金 → 明日 土 休み → H
        assert classify_night(date(2026, 4, 10)) == "H"

    def test_saturday_is_high(self) -> None:
        # 2026-04-11 土 → 明日 日 休み → H
        assert classify_night(date(2026, 4, 11)) == "H"

    def test_normal_sunday_is_mid(self) -> None:
        # 2026-04-12 日 → 今日休み・明日 月 平日 → M
        assert classify_night(date(2026, 4, 12)) == "M"

    def test_weekday_mon_to_thu_is_low(self) -> None:
        # 2026-04-13(月)..16(木) いずれも平日通常 → L
        for d in (date(2026, 4, 13), date(2026, 4, 14), date(2026, 4, 15), date(2026, 4, 16)):
            assert classify_night(d) == "L"

    def test_wed_before_thursday_holiday_is_high(self) -> None:
        # 2025-12-31 水 → 明日 2026-01-01(木・元日) 休み → H
        assert classify_night(date(2025, 12, 31)) == "H"

    def test_sunday_before_monday_holiday_is_high(self) -> None:
        # 2026-01-11 日 → 明日 2026-01-12(月・成人の日) 休み → H
        assert classify_night(date(2026, 1, 11)) == "H"

    def test_holiday_thursday_before_work_friday_is_mid(self) -> None:
        # 2026-01-01(木・元日) → 今日休み・明日 1/2(金) は平日(祝日でない) → M
        assert classify_night(date(2026, 1, 1)) == "M"

    def test_gw_middle_day_is_high(self) -> None:
        # 2026-05-04(月・みどりの日) → 明日 5/5(火・こどもの日) 休み → H
        assert classify_night(date(2026, 5, 4)) == "H"

    def test_gw_last_day_before_workday_is_mid(self) -> None:
        # 2026-05-06(水・振替休日) → 明日 5/7(木) 平日 → M（連休最終日タイプ）
        assert classify_night(date(2026, 5, 6)) == "M"


class TestDayOff:
    def test_weekend_and_holiday_are_off(self) -> None:
        assert day_off(date(2026, 4, 11))  # 土
        assert day_off(date(2026, 4, 12))  # 日
        assert day_off(date(2026, 4, 29))  # 昭和の日(水)

    def test_customary_off_is_not_day_off(self) -> None:
        # 慣習休業は classify 用 day_off には含めない: 2025-12-30(火) は平日扱い
        assert not day_off(date(2025, 12, 30))
        # お盆の平日 2025-08-14(木) も day_off ではない
        assert not day_off(date(2025, 8, 14))

    def test_normal_weekday_not_off(self) -> None:
        assert not day_off(date(2026, 4, 13))  # 月


class TestSpecialBlock:
    def test_obon(self) -> None:
        assert special_block(date(2025, 8, 13)) == "obon"
        assert special_block(date(2025, 8, 14)) == "obon"
        assert special_block(date(2025, 8, 15)) == "obon"
        assert special_block(date(2025, 8, 12)) is None
        assert special_block(date(2025, 8, 16)) is None  # 週末だが obon コア外

    def test_nye(self) -> None:
        assert special_block(date(2025, 12, 29)) == "nye"
        assert special_block(date(2025, 12, 31)) == "nye"
        assert special_block(date(2026, 1, 1)) == "nye"
        assert special_block(date(2026, 1, 3)) == "nye"
        assert special_block(date(2025, 12, 28)) is None
        assert special_block(date(2026, 1, 4)) is None

    def test_gw_showa_day_isolated(self) -> None:
        # 2026-04-29(水・昭和の日) は単独祝日だが GW 窓に入るので gw
        assert special_block(date(2026, 4, 29)) == "gw"

    def test_gw_main_block(self) -> None:
        # 2026-05-02(土)〜5/6(水) の連休は gw
        for d in (date(2026, 5, 2), date(2026, 5, 4), date(2026, 5, 6)):
            assert special_block(d) == "gw"

    def test_gw_valley_workday_is_not_special(self) -> None:
        # 2026-05-01(金) は GW の谷間の平日 → 休業日でないので None
        assert special_block(date(2026, 5, 1)) is None

    def test_normal_weekend_not_special(self) -> None:
        assert special_block(date(2026, 4, 18)) is None  # 土
        assert special_block(date(2026, 4, 19)) is None  # 日


class TestNightDateOf:
    def test_evening_belongs_to_same_day(self) -> None:
        assert night_date_of(datetime(2026, 5, 2, 19, 0)) == date(2026, 5, 2)
        assert night_date_of(datetime(2026, 5, 2, 23, 59)) == date(2026, 5, 2)

    def test_after_midnight_belongs_to_previous_evening(self) -> None:
        assert night_date_of(datetime(2026, 5, 3, 0, 0)) == date(2026, 5, 2)
        assert night_date_of(datetime(2026, 5, 3, 2, 0)) == date(2026, 5, 2)
        assert night_date_of(datetime(2026, 5, 3, 5, 59)) == date(2026, 5, 2)

    def test_early_morning_boundary_at_six(self) -> None:
        # 06:00 は新しい昼のセッション（前夜には属さない）
        assert night_date_of(datetime(2026, 5, 3, 6, 0)) == date(2026, 5, 3)

    def test_tz_aware_converted_to_jst(self) -> None:
        # UTC 2026-05-02 18:00 = JST 2026-05-03 03:00 → 前夜 5/2
        aware = datetime(2026, 5, 2, 18, 0, tzinfo=timezone.utc)
        assert night_date_of(aware) == date(2026, 5, 2)
