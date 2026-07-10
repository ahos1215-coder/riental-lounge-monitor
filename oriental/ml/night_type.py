"""夜タイプ分類（v2 予測の軸）と特別期間ブロック判定。純関数のみ・I/O なし。

v2 予測の中核となる「夜タイプ」= 予測すべき曜日ではなく「その夜の混み方」を決める軸。
139k 行・8 店で実測したところ、平日通常=1.00 / 日曜=1.20 / 金土=3.56 /
祝前日(金土以外)=3.55（n=50 夜）で、祝前日は金土と実質同一だった。つまり軸は
「曜日」ではなく「今夜が休前夜か / 今日が休日か」という 2 ビットで決まる:

    day_off(x) = (x.weekday() >= 5) or jpholiday.is_holiday(x)   # 土日 or 法定祝日
    明日が休み(tomorrow_off) → 'H'   （金 / 祝前日 / 土 / 連休中日タイプ = 最も混む）
    それ以外で今日が休み(today_off) → 'M'  （日曜 / 連休最終日タイプ）
    どちらでもない → 'L'                     （平日通常 = 最も空く）

注意: classify_night の day_off は「土日 or jpholiday のみ」で判定する。お盆・年末年始・
GW などの慣習的休業(is_customary_off)は classify_night には入れない（純粋に混雑の軸を
決めるのは休前夜構造であり、慣習期間はイベント異常として special_block で別枠管理し、
テンプレ/スケールの参照集合から除外する — 汚染ガード）。

夜の日付(night_date)は -6h シフト規約: 00:00-05:59 のスロットは前夜のセッションに属する
（postprocess.py の NIGHT_SESSION_SHIFT_HOURS=6 と同一規約）。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import jpholiday

try:
    from oriental.ml.holiday_calendar import is_off_day
except ModuleNotFoundError:
    # 最小依存環境(GHAのbuild-templates/snapshotジョブ=stdlib+jpholidayのみ)では、
    # パッケージ経由importが oriental/__init__.py の flask 等を引き込んで失敗する。
    # holiday_calendar.py 自体は stdlib+jpholiday のみなのでファイル直読みで代替する。
    import importlib.util as _ilu
    from pathlib import Path as _Path

    _p = _Path(__file__).with_name("holiday_calendar.py")
    _spec = _ilu.spec_from_file_location("_holiday_calendar_standalone", _p)
    _m = _ilu.module_from_spec(_spec)
    assert _spec and _spec.loader
    _spec.loader.exec_module(_m)
    is_off_day = _m.is_off_day

__all__ = ["classify_night", "special_block", "night_date_of", "day_off"]

JST = timezone(timedelta(hours=9))

# 夜セッションの -6h シフト（深夜0-5時台を前夜の続きとして扱う）。postprocess と同一。
NIGHT_SESSION_SHIFT_HOURS = 6

# お盆 (8/13-15)。
_OBON_RANGE_MD = ((8, 13), (8, 15))
# 年末年始 (12/29 以降 / 1/3 以前)。
_NYE_END_MONTH_DAY = (12, 29)
_NYE_START_MONTH_DAY = (1, 3)
# 連休ブロック探索の最大日数（片側）。
_MAX_SEARCH_DAYS = 14


def day_off(d: date) -> bool:
    """土日 or 法定祝日か（classify_night 用の 1 ビット判定）。

    慣習的休業(お盆/年末年始/GW の谷間の平日)は含めない — それは special_block の領分。
    """
    return d.weekday() >= 5 or jpholiday.is_holiday(d)


def classify_night(d: date) -> str:
    """夜 d を 'H'（明日休み=最も混む）/'M'（今日休み・明日仕事）/'L'（平日通常）に分類する。

    d はその夜が「始まった日」（19:00 側の暦日 = night_date）。2 ビット規則:
        tomorrow_off → 'H' / today_off → 'M' / else 'L'
    """
    if day_off(d + timedelta(days=1)):
        return "H"
    if day_off(d):
        return "M"
    return "L"


def _off_block_bounds(d: date) -> tuple[date, date]:
    """d を含む連続「休業日(is_off_day)」ブロックの開始日・終了日を返す。

    is_off_day は土日 + 法定祝日 + 振替 + 慣習休業(お盆/年末年始)を含む
    （holiday_calendar と同一）。GW の連休クラスタ検出に使う。
    """
    start = d
    for _ in range(_MAX_SEARCH_DAYS):
        prev = start - timedelta(days=1)
        if is_off_day(prev):
            start = prev
        else:
            break
    end = d
    for _ in range(_MAX_SEARCH_DAYS):
        nxt = end + timedelta(days=1)
        if is_off_day(nxt):
            end = nxt
        else:
            break
    return start, end


def _gw_window(year: int) -> tuple[date, date]:
    """その年の GW 判定窓 [4/29, 5/6]。この範囲に重なる連休ブロックを GW とみなす。"""
    return date(year, 4, 29), date(year, 5, 6)


def special_block(d: date) -> str | None:
    """夜 d が特別期間(イベント異常)に属するなら 'gw'|'obon'|'nye'、そうでなければ None。

    - 'obon': 8/13-15
    - 'nye' : 12/29-1/3
    - 'gw'  : 4/29-5/6 を含む連続休業ブロック（Showa Day 単独祝日や、5/2-5/6 の連休を含む）

    special_block の夜はテンプレ/スケールの参照集合から除外する（汚染ガード）。ただし
    「今夜がたまたま special_block」の場合でも v2 予測自体は該当タイプのテンプレで出し、
    出力に special_block をタグ付けして観測可能にする。
    """
    md = (d.month, d.day)
    if _OBON_RANGE_MD[0] <= md <= _OBON_RANGE_MD[1]:
        return "obon"
    if (d.month == 12 and d.day >= _NYE_END_MONTH_DAY[1]) or (
        d.month == 1 and d.day <= _NYE_START_MONTH_DAY[1]
    ):
        return "nye"
    if is_off_day(d):
        start, end = _off_block_bounds(d)
        win_start, win_end = _gw_window(d.year)
        # ブロック [start, end] が GW 窓 [win_start, win_end] と重なるか。
        if start <= win_end and end >= win_start:
            return "gw"
    return None


def night_date_of(ts: datetime) -> date:
    """タイムスタンプ ts が属する「夜」の暦日を返す（-6h シフト規約）。

    00:00-05:59 のスロットは前夜のセッション(前日 19:00 発)に属する。tz-aware なら JST に
    変換してから判定する（naive は JST 前提）。postprocess の -6h シフトと同一規約。
    例: 2026-05-02 02:00 → 2026-05-01 の夜 / 2026-05-02 19:00 → 2026-05-02 の夜。
    """
    if getattr(ts, "tzinfo", None) is not None:
        ts = ts.astimezone(JST)
    return (ts - timedelta(hours=NIGHT_SESSION_SHIFT_HOURS)).date()
