"""連休ブロック境界の定義が night_type と holiday_calendar で一致していることの番犬。

night_type._off_block_bounds は holiday_calendar.get_holiday_block と同じ
「is_off_day で前後に最大14日歩く」走査を持っていた（重複実装）。共通化しても
両者の答えがずれないことを、GW / お盆 / 年末年始の境界日で固定する。

お盆・年末年始の期間定数も両モジュールで同値であること（片方だけ変更する事故の防止）を
併せて検証する。
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from oriental.ml import holiday_calendar, night_type


def _boundary_dates() -> list[date]:
    out: list[date] = []
    for year in (2025, 2026, 2027):
        # GW 前後 / お盆前後 / 年末年始前後を日単位で総なめする
        for start, days in (
            (date(year, 4, 24), 21),
            (date(year, 8, 8), 14),
            (date(year, 12, 24), 20),
        ):
            out.extend(start + timedelta(days=i) for i in range(days))
    return out


@pytest.mark.parametrize("d", _boundary_dates(), ids=str)
def test_off_block_bounds_agrees_with_get_holiday_block(d: date):
    length, position = holiday_calendar.get_holiday_block(d)

    if not holiday_calendar.is_off_day(d):
        assert (length, position) == (0, None)
        return

    start, end = night_type._off_block_bounds(d)
    assert start <= d <= end
    assert (end - start).days + 1 == length, f"{d}: block bounds disagree with block length"

    expected_position = 0.5 if length == 1 else (d - start).days / (length - 1)
    assert position == pytest.approx(expected_position)


def test_customary_off_period_constants_are_shared():
    """お盆・年末年始の期間と探索日数が2モジュールで同値であること。"""
    assert night_type._OBON_RANGE_MD == holiday_calendar.OBON_RANGE_MD
    assert night_type._NYE_END_MONTH_DAY == holiday_calendar.NEW_YEAR_RANGE_END_MD
    assert night_type._NYE_START_MONTH_DAY == holiday_calendar.NEW_YEAR_RANGE_START_MD
    assert night_type._MAX_SEARCH_DAYS == holiday_calendar._MAX_SEARCH_DAYS


def test_special_block_labels_at_known_boundaries():
    """special_block のラベル（obon/nye/gw/None）は共通化前後で不変。"""
    assert night_type.special_block(date(2026, 8, 12)) is None
    assert night_type.special_block(date(2026, 8, 13)) == "obon"
    assert night_type.special_block(date(2026, 8, 15)) == "obon"
    assert night_type.special_block(date(2026, 8, 16)) is None

    assert night_type.special_block(date(2026, 12, 28)) is None
    assert night_type.special_block(date(2026, 12, 29)) == "nye"
    assert night_type.special_block(date(2027, 1, 3)) == "nye"
    assert night_type.special_block(date(2027, 1, 4)) is None

    # 2026 GW: 4/29(昭和の日・単独) と 5/2-5/6 の連休クラスタ
    assert night_type.special_block(date(2026, 4, 29)) == "gw"
    assert night_type.special_block(date(2026, 5, 4)) == "gw"
    assert night_type.special_block(date(2026, 5, 6)) == "gw"
    assert night_type.special_block(date(2026, 5, 7)) is None
