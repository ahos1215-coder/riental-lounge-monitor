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

# 休業日の定義・お盆/年末年始の期間・連休ブロック走査は holiday_calendar が単一ソース。
try:
    from oriental.ml.holiday_calendar import (
        _MAX_SEARCH_DAYS,
        NEW_YEAR_RANGE_END_MD as _NYE_END_MONTH_DAY,
        NEW_YEAR_RANGE_START_MD as _NYE_START_MONTH_DAY,
        OBON_RANGE_MD as _OBON_RANGE_MD,
        is_off_day,
        off_block_bounds as _off_block_bounds,
    )
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
    _off_block_bounds = _m.off_block_bounds
    _OBON_RANGE_MD = _m.OBON_RANGE_MD
    _NYE_END_MONTH_DAY = _m.NEW_YEAR_RANGE_END_MD
    _NYE_START_MONTH_DAY = _m.NEW_YEAR_RANGE_START_MD
    _MAX_SEARCH_DAYS = _m._MAX_SEARCH_DAYS

__all__ = [
    "classify_night",
    "special_block",
    "night_date_of",
    "day_off",
    "is_special_night",
    "is_holiday_influenced_night",
    "reference_offsets",
]

JST = timezone(timedelta(hours=9))

# 夜セッションの -6h シフト（深夜0-5時台を前夜の続きとして扱う）。postprocess と同一。
NIGHT_SESSION_SHIFT_HOURS = 6


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


# 暦で決まるイベントの夜（月, 日）。クリスマスイブ・クリスマス・ハロウィン。
EVENT_NIGHTS_MD = frozenset({(12, 24), (12, 25), (10, 31)})
# この日数以上の連休（シルバーウィーク等）の夜と、その前夜を特別な夜とみなす。
LONG_HOLIDAY_MIN_DAYS = 4
# 「先週の同じ夜」を参照する特徴・ブレンドが手本にしてよい夜の候補（日数。近い順）。
# 7日前が祝日がらみ、またはデータが無い（2026-09-06〜16 の収集停止など）ときに順に下がる。
REFERENCE_OFFSETS_DAYS = (7, 14, 21, 28)


def _off_block_length(d: date) -> int:
    """d を含む連続休業ブロックの日数（休業日でなければ 0）。holiday_calendar.get_holiday_block と同じ数え方。"""
    if not is_off_day(d):
        return 0
    start, end = _off_block_bounds(d)
    return (end - start).days + 1


def is_special_night(d: date) -> bool:
    """夜 d が、去年の同じ夜と比べる価値のある「特別な夜」か（2026-09-26 追加）。

    - special_block: 年末年始（12/29-1/3）・お盆（8/13-15）・GW の連休
    - 4連休以上の連休に含まれる夜、または翌日から4連休以上が始まる夜（連休前夜）
    - クリスマスイブ・クリスマス・ハロウィン

    scripts/cleanup_old_logs.py はこの夜を2年間残す（DB 容量の都合で普段の夜は約8〜9か月で消える）。
    """
    if special_block(d) is not None:
        return True
    if (d.month, d.day) in EVENT_NIGHTS_MD:
        return True
    return any(_off_block_length(day) >= LONG_HOLIDAY_MIN_DAYS for day in (d, d + timedelta(days=1)))


def is_holiday_influenced_night(d: date) -> bool:
    """夜 d の混み方が祝日のせいで普段と違っていた可能性があるか（2026-09-29 追加）。

    祝日の夜・祝日の前夜（翌日が祝日）・特別な夜（is_special_night）。ただの土日は含めない
    （土曜は先週の土曜と比べれば足りる。混み方を変えるのは「いつもは平日なのに休み」の側）。

    「先週の同じ夜」を手本にする特徴（preprocess の same_dow_last_week_total）とブレンド
    （postprocess.blend_with_baseline）は、手本の夜がこれに当たるときは使わない。2026-09-28/29 に
    シルバーウィーク（9/19-23）の翌週の予測が、連休の夜（普段の約5倍の人出）を手本にして全店で
    数倍に膨らんだ（reference_offsets）。
    """
    return (
        jpholiday.is_holiday(d)
        or jpholiday.is_holiday(d + timedelta(days=1))
        or is_special_night(d)
    )


def reference_offsets(target_night: date) -> tuple[int, ...]:
    """夜 target_night の手本として使ってよい「同じ曜日の過去の夜」が何日前か（近い順）。

    REFERENCE_OFFSETS_DAYS（7/14/21/28日前）のうち、祝日がらみ（is_holiday_influenced_night）の夜を
    除いたもの。使う側は、この順に見て**実測がある最初の夜**を手本にする（データが無い夜も飛ばす）。
    全部だめなら手本なし（特徴は NaN、ブレンドはしない）。

    データの有無まで見るのは、手本なしの行を減らすため。手本なしの行は preprocess の末尾で「その表の
    中央値」に埋められ、推論時の表（直近8日＋今夜）に連休の夜が入っている週は、その中央値が膨らむ
    （2026-09-29、14日前で止める版では 9/15 が収集停止で欠けていた福岡の予測が普段の約2倍のまま
    だった）。対象の夜そのものが祝日がらみかどうかは見ない（それは祝日系の特徴の役目。ここで直すのは
    「手本の汚れ」だけ）。
    """
    return tuple(
        days
        for days in REFERENCE_OFFSETS_DAYS
        if not is_holiday_influenced_night(target_night - timedelta(days=days))
    )


def night_date_of(ts: datetime) -> date:
    """タイムスタンプ ts が属する「夜」の暦日を返す（-6h シフト規約）。

    00:00-05:59 のスロットは前夜のセッション(前日 19:00 発)に属する。tz-aware なら JST に
    変換してから判定する（naive は JST 前提）。postprocess の -6h シフトと同一規約。
    例: 2026-05-02 02:00 → 2026-05-01 の夜 / 2026-05-02 19:00 → 2026-05-02 の夜。
    """
    if getattr(ts, "tzinfo", None) is not None:
        ts = ts.astimezone(JST)
    return (ts - timedelta(hours=NIGHT_SESSION_SHIFT_HOURS)).date()
