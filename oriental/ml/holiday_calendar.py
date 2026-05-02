"""
連休クラスタ判定。

「連休」= 連続して休業日扱いとなる日のかたまり。
休業日 = 土日 + 法定祝日 + 振替休日 + 慣習的休業期間 (お盆 8/13-15、年末年始 12/29-1/3)。

`get_holiday_block(d)` は当日を含む連続休業ブロックの長さ (block_length) と、
ブロック内の相対位置 (block_position 0.0=初日 / 1.0=最終日) を返す。

例 (2026 GW):
  4/29 (水・昭和の日) → 単独祝日 → length=1, position=0.5
  5/2 (土) 〜 5/6 (水・振替休日)  → 5 連休
    5/2 → length=5, position=0.0
    5/4 → length=5, position=0.5
    5/6 → length=5, position=1.0

平日 (休業日でない日): length=0, position=None。

Schema v6 (2026-05〜) で `holiday_block_length` / `holiday_block_position`
として preprocess.py の特徴量に投入される。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

import jpholiday


# 慣習的に多くの企業・店舗が休業する固定期間 (法定祝日ではない)
# 月日のタプル (m, d) で範囲を表現する。年をまたぐ年末年始は 2 範囲に分けて判定。
OBON_RANGE_MD = ((8, 13), (8, 15))  # お盆: 8/13 - 8/15
NEW_YEAR_RANGE_END_MD = (12, 29)  # 年末: 12/29 以降
NEW_YEAR_RANGE_START_MD = (1, 3)  # 年始: 1/3 以前

# 連休ブロック検索の最大日数 (片側)。実際の最長は ~10 日程度なので 14 日で十分。
_MAX_SEARCH_DAYS = 14


def is_customary_off(d: date) -> bool:
    """お盆 (8/13-15) や年末年始 (12/29-1/3) など、慣習的な休業日かどうか。"""
    md = (d.month, d.day)
    if OBON_RANGE_MD[0] <= md <= OBON_RANGE_MD[1]:
        return True
    if d.month == 12 and d.day >= NEW_YEAR_RANGE_END_MD[1]:
        return True
    if d.month == 1 and d.day <= NEW_YEAR_RANGE_START_MD[1]:
        return True
    return False


def is_off_day(d: date) -> bool:
    """休業日 (土日 / 法定祝日 / 振替休日 / 慣習的休業日) かどうか。"""
    if d.weekday() >= 5:  # 5=Saturday, 6=Sunday
        return True
    if jpholiday.is_holiday(d):
        return True
    if is_customary_off(d):
        return True
    return False


def get_holiday_block(target_date: date) -> tuple[int, Optional[float]]:
    """
    target_date を含む連続休業ブロックの長さと位置を返す。

    Returns:
        (block_length, block_position):
            block_length: 0 なら平日 (休業日でない)、>=1 なら連続休業日数
            block_position: 0.0 (ブロック初日) ~ 1.0 (ブロック最終日)、平日なら None
                            length=1 の単発休日は 0.5 とする
    """
    if not is_off_day(target_date):
        return (0, None)

    # ブロックの開始日 (target から後ろに歩く)
    start = target_date
    for _ in range(_MAX_SEARCH_DAYS):
        prev = start - timedelta(days=1)
        if is_off_day(prev):
            start = prev
        else:
            break

    # ブロックの終了日 (target から前に歩く)
    end = target_date
    for _ in range(_MAX_SEARCH_DAYS):
        nxt = end + timedelta(days=1)
        if is_off_day(nxt):
            end = nxt
        else:
            break

    block_length = (end - start).days + 1
    if block_length == 1:
        block_position: Optional[float] = 0.5
    else:
        idx = (target_date - start).days
        block_position = idx / (block_length - 1)

    return (block_length, block_position)


def is_long_holiday(target_date: date, threshold: int = 4) -> bool:
    """target_date が「連休」(block_length >= threshold) に含まれるかどうか。"""
    length, _ = get_holiday_block(target_date)
    return length >= threshold
