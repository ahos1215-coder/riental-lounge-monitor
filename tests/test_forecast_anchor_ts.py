"""番犬: _anchor_to_tonight のスロット照合が、予測点の ts 表記（JST / UTC / naive）に
依存しないこと。

`_as_ts` を oriental/ml/_num.py へ統一した際、tz 付き入力を tz_convert する形
（postprocess 側の挙動）に寄せた。JST はオフセットが時間単位なので floor(15min) の
結果＝同じ瞬間は変わらない、というのがここで固定したい性質。
"""

from __future__ import annotations

import pandas as pd

from oriental.ml.forecast_service import _anchor_to_tonight

TZ = "Asia/Tokyo"
FREQ = 15


def _history(now: pd.Timestamp) -> pd.DataFrame:
    """now より前の 4 スロット分の実測（予測の 2 倍の来客）。"""
    rows = []
    for i in range(4, 0, -1):
        rows.append({"ts": now - pd.Timedelta(minutes=FREQ * i), "total": 20.0})
    return pd.DataFrame(rows)


def _points(now: pd.Timestamp, fmt: str) -> list[dict]:
    points = []
    for i in range(4, 0, -1):  # 経過済みスロット（予測 10 に対し実測 20）
        ts = now - pd.Timedelta(minutes=FREQ * i)
        points.append({"ts": _fmt(ts, fmt), "men_pred": 5.0, "women_pred": 5.0, "total_pred": 10.0})
    for i in range(1, 5):  # これからのスロット
        ts = now + pd.Timedelta(minutes=FREQ * i)
        points.append({"ts": _fmt(ts, fmt), "men_pred": 5.0, "women_pred": 5.0, "total_pred": 10.0})
    return points


def _fmt(ts: pd.Timestamp, fmt: str) -> str:
    if fmt == "jst":
        return ts.isoformat()
    if fmt == "utc":
        return ts.tz_convert("UTC").isoformat()
    if fmt == "naive":
        return ts.tz_localize(None).isoformat()
    raise ValueError(fmt)


def test_ts表記が違っても補正結果が一致する():
    now = pd.Timestamp.now(tz=TZ).floor(f"{FREQ}min")
    hist = _history(now)

    results = {}
    for fmt in ("jst", "utc", "naive"):
        adjusted = _anchor_to_tonight(hist, _points(now, fmt), FREQ, TZ)
        results[fmt] = [
            (round(p["total_pred"], 6), p.get("anchor_effective")) for p in adjusted
        ]

    assert results["jst"] == results["utc"] == results["naive"]
    # 実測が予測の2倍 -> 直後のスロットは 2.0 倍（上限クランプ）方向へ補正される
    assert any(v[1] is not None and v[1] > 1.0 for v in results["jst"])
