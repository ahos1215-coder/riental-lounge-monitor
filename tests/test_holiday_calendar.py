"""連休クラスタ判定のテスト。

期待値の根拠:
- 2026 GW: 4/29(水) は祝日だが 4/30(木)・5/1(金) が平日なので単発祝日 (length=1)。
  5/2(土)〜5/6(水・5/3 振替) が 5 連休。
- 2025-2026 年末年始: 12/27(土)・28(日)・29(月)〜31(水) が customary、1/1(木) が祝日、
  1/2(金)・3(土) が customary、1/4(日) も休、1/5(月) が平日。
  ブロック: 12/27〜1/4 = 9 連休。
- 2025 お盆: 8/13(水)〜15(金) が customary。前後の 8/16(土)・17(日) で +2、
  8/12(火) が平日。よってブロック: 8/13〜17 = 5 連休。
- 単発祝日: 2026/11/3(火・文化の日) は前後が平日なので length=1。
- 通常週末: 2026/4/11(土)〜12(日) は length=2。
"""

from __future__ import annotations

from datetime import date

import pytest

from oriental.ml.holiday_calendar import (
    get_holiday_block,
    is_customary_off,
    is_long_holiday,
    is_off_day,
)


class TestIsCustomaryOff:
    def test_obon_inclusive(self) -> None:
        assert is_customary_off(date(2025, 8, 13))
        assert is_customary_off(date(2025, 8, 14))
        assert is_customary_off(date(2025, 8, 15))

    def test_obon_boundary(self) -> None:
        assert not is_customary_off(date(2025, 8, 12))
        assert not is_customary_off(date(2025, 8, 16))

    def test_year_end(self) -> None:
        assert is_customary_off(date(2025, 12, 29))
        assert is_customary_off(date(2025, 12, 30))
        assert is_customary_off(date(2025, 12, 31))
        assert not is_customary_off(date(2025, 12, 28))

    def test_new_year(self) -> None:
        assert is_customary_off(date(2026, 1, 1))  # 元日 (also jp_holiday)
        assert is_customary_off(date(2026, 1, 2))
        assert is_customary_off(date(2026, 1, 3))
        assert not is_customary_off(date(2026, 1, 4))

    def test_normal_weekday(self) -> None:
        assert not is_customary_off(date(2026, 4, 7))  # 火


class TestIsOffDay:
    def test_weekday_workday(self) -> None:
        assert not is_off_day(date(2026, 4, 7))  # 火曜
        assert not is_off_day(date(2026, 4, 30))  # 木曜 (GW中の谷間)
        assert not is_off_day(date(2026, 5, 1))  # 金曜 (GW中の谷間)

    def test_saturday(self) -> None:
        assert is_off_day(date(2026, 4, 11))

    def test_sunday(self) -> None:
        assert is_off_day(date(2026, 4, 12))

    def test_jp_holiday(self) -> None:
        assert is_off_day(date(2026, 4, 29))  # 昭和の日 (Wed)
        assert is_off_day(date(2026, 11, 3))  # 文化の日 (Tue)

    def test_obon(self) -> None:
        assert is_off_day(date(2025, 8, 13))  # Wed customary

    def test_year_end(self) -> None:
        assert is_off_day(date(2025, 12, 30))  # Tue customary


class TestGetHolidayBlock:
    def test_workday_returns_zero_and_none(self) -> None:
        length, position = get_holiday_block(date(2026, 4, 7))  # Tue
        assert length == 0
        assert position is None

    def test_normal_weekend(self) -> None:
        # 2026/4/11 (土) - 12 (日) で length=2
        length_sat, pos_sat = get_holiday_block(date(2026, 4, 11))
        length_sun, pos_sun = get_holiday_block(date(2026, 4, 12))
        assert length_sat == 2
        assert length_sun == 2
        assert pos_sat == 0.0
        assert pos_sun == 1.0

    def test_isolated_weekday_holiday(self) -> None:
        # 2026/11/3 (火・文化の日) — 前後平日なので length=1
        length, position = get_holiday_block(date(2026, 11, 3))
        assert length == 1
        assert position == 0.5

    def test_gw_2026_block(self) -> None:
        # 2026 GW: 5/2(土) - 5/6(水・5/3 振替休日) = 5 連休
        # 4/29(水) は祝日だが 4/30(木) が平日で分断 → 別ブロック (length=1)
        length_429, pos_429 = get_holiday_block(date(2026, 4, 29))
        assert length_429 == 1
        assert pos_429 == 0.5

        # GW メインブロック: 5/2〜5/6 = 5 日
        length_502, pos_502 = get_holiday_block(date(2026, 5, 2))
        length_504, pos_504 = get_holiday_block(date(2026, 5, 4))
        length_506, pos_506 = get_holiday_block(date(2026, 5, 6))
        assert length_502 == 5
        assert length_504 == 5
        assert length_506 == 5
        assert pos_502 == 0.0
        assert pos_506 == 1.0
        # 中日 (3/4 日目): position は 2/4 = 0.5
        assert pytest.approx(pos_504, abs=0.01) == 0.5

    def test_year_end_2025_2026_block(self) -> None:
        # 2025/12/27(土) - 2026/1/4(日) = 9 連休
        # 12/27, 12/28 (週末) → 12/29-31 (customary) → 1/1 (元日) → 1/2-3 (customary) → 1/4 (日)
        length_27, pos_27 = get_holiday_block(date(2025, 12, 27))
        length_104, pos_104 = get_holiday_block(date(2026, 1, 4))
        assert length_27 == 9
        assert length_104 == 9
        assert pos_27 == 0.0
        assert pos_104 == 1.0

    def test_obon_2025_block(self) -> None:
        # 2025 お盆: 8/13(水)-15(金) customary + 8/16(土)-17(日) 週末 = 5 連休
        # 8/12(火) が平日なので開始は 8/13。
        length_813, pos_813 = get_holiday_block(date(2025, 8, 13))
        length_817, pos_817 = get_holiday_block(date(2025, 8, 17))
        assert length_813 == 5
        assert length_817 == 5
        assert pos_813 == 0.0
        assert pos_817 == 1.0


class TestIsLongHoliday:
    def test_workday_is_not_long_holiday(self) -> None:
        assert not is_long_holiday(date(2026, 4, 7))

    def test_normal_weekend_not_long_holiday(self) -> None:
        assert not is_long_holiday(date(2026, 4, 11))  # length=2 < 4

    def test_gw_is_long_holiday(self) -> None:
        assert is_long_holiday(date(2026, 5, 4))  # length=5 >= 4

    def test_year_end_is_long_holiday(self) -> None:
        assert is_long_holiday(date(2025, 12, 30))  # length=9 >= 4

    def test_obon_is_long_holiday(self) -> None:
        assert is_long_holiday(date(2025, 8, 14))  # length=5 >= 4

    def test_threshold_override(self) -> None:
        # threshold=10 にすれば GW でも long_holiday=False
        assert not is_long_holiday(date(2026, 5, 4), threshold=10)
