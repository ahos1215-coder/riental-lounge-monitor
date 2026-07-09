"""Unit tests for the closed-loop serving post-processing:
late-night decay clamp + seasonal-naive baseline blend (oriental/ml/postprocess.py),
plus the ForecastService wiring (weights-file fallback → w_ml=1.0).

All synthetic / no network.
"""

import logging

import numpy as np
import pandas as pd
import pytest

from oriental.ml.postprocess import (
    _night_bucket,
    actual_slot_map,
    blend_with_baseline,
    late_night_clamp,
    same_slot_stats,
    same_slot_stats_by_bucket,
)

TZ = "Asia/Tokyo"


def _hist(rows):
    """rows: list of (ts_str, men, women, total) -> tz-aware history DataFrame."""
    return pd.DataFrame(
        [
            {"ts": pd.Timestamp(ts, tz=TZ), "men": m, "women": w, "total": t}
            for ts, m, w, t in rows
        ]
    )


def _pt(ts_str, men, women):
    ts = pd.Timestamp(ts_str, tz=TZ)
    return {
        "ts": ts.isoformat(),
        "men_pred": float(men),
        "women_pred": float(women),
        "total_pred": float(men + women),
    }


# --------------------------- late_night_clamp ---------------------------

def test_clamp_zero_history_collapses_to_zero():
    # gangnam-like: closed after 00:30, every recent night ~0 at that slot.
    hist = _hist(
        [
            ("2026-07-01 00:30", 0, 0, 0),
            ("2026-07-02 00:30", 0, 0, 0),
            ("2026-07-03 00:30", 0, 0, 0),
        ]
    )
    points = [_pt("2026-07-08 00:30", 25, 25)]  # ML says 50
    out, n = late_night_clamp(points, hist, TZ, freq_min=15)
    assert n == 1
    assert out[0]["total_pred"] == 0.0
    assert out[0]["men_pred"] == 0.0
    assert out[0]["women_pred"] == 0.0
    assert out[0]["clamped"] is True
    assert out[0]["clamp_cap"] == 0.0


def test_clamp_headroom_caps_overshoot_and_scales_gender():
    hist = _hist(
        [
            ("2026-07-01 23:30", 5, 5, 10),  # max total = 10
            ("2026-07-02 23:30", 4, 4, 8),
            ("2026-07-03 23:30", 3, 3, 6),
        ]
    )
    # cap = 1.3 * 10 = 13
    over = [_pt("2026-07-08 23:30", 25, 25)]  # 50 > 13
    out, n = late_night_clamp(over, hist, TZ)
    assert n == 1
    assert out[0]["total_pred"] == pytest.approx(13.0)
    assert out[0]["men_pred"] == pytest.approx(6.5)  # scaled proportionally
    assert out[0]["women_pred"] == pytest.approx(6.5)


def test_clamp_leaves_under_cap_untouched():
    hist = _hist(
        [
            ("2026-07-01 23:30", 5, 5, 10),
            ("2026-07-02 23:30", 4, 4, 8),
            ("2026-07-03 23:30", 3, 3, 6),
        ]
    )
    under = [_pt("2026-07-08 23:30", 3, 2)]  # total 5 < cap 13
    out, n = late_night_clamp(under, hist, TZ)
    assert n == 0
    assert out[0]["total_pred"] == pytest.approx(5.0)
    assert "clamped" not in out[0]


def test_clamp_headroom_env_tunable(monkeypatch):
    monkeypatch.setenv("FORECAST_LATE_CLAMP_HEADROOM", "2.0")
    hist = _hist(
        [
            ("2026-07-01 23:30", 0, 0, 10),
            ("2026-07-02 23:30", 0, 0, 10),
            ("2026-07-03 23:30", 0, 0, 10),
        ]
    )
    out, n = late_night_clamp([_pt("2026-07-08 23:30", 40, 40)], hist, TZ)  # 80 > 20
    assert n == 1
    assert out[0]["total_pred"] == pytest.approx(20.0)  # 2.0 * 10


def test_clamp_skips_when_few_nights():
    hist = _hist(
        [
            ("2026-07-01 01:00", 0, 0, 0),
            ("2026-07-02 01:00", 0, 0, 0),
        ]
    )  # only 2 nights < CLAMP_MIN_NIGHTS (3)
    out, n = late_night_clamp([_pt("2026-07-08 01:00", 25, 25)], hist, TZ)
    assert n == 0
    assert out[0]["total_pred"] == pytest.approx(50.0)


def test_clamp_untouched_before_23():
    hist = _hist(
        [
            ("2026-07-01 21:00", 0, 0, 1),
            ("2026-07-02 21:00", 0, 0, 1),
            ("2026-07-03 21:00", 0, 0, 1),
        ]
    )
    out, n = late_night_clamp([_pt("2026-07-08 21:00", 50, 50)], hist, TZ)
    assert n == 0
    assert out[0]["total_pred"] == pytest.approx(100.0)


def test_clamp_no_history_is_noop():
    assert late_night_clamp([_pt("2026-07-08 00:30", 25, 25)], None, TZ) == (
        [_pt("2026-07-08 00:30", 25, 25)],
        0,
    )
    empty = pd.DataFrame(columns=["ts", "total"])
    out, n = late_night_clamp([_pt("2026-07-08 00:30", 25, 25)], empty, TZ)
    assert n == 0


def test_clamp_off_switch(monkeypatch):
    monkeypatch.setenv("FORECAST_LATE_CLAMP", "0")
    hist = _hist(
        [
            ("2026-07-01 00:30", 0, 0, 0),
            ("2026-07-02 00:30", 0, 0, 0),
            ("2026-07-03 00:30", 0, 0, 0),
        ]
    )
    out, n = late_night_clamp([_pt("2026-07-08 00:30", 25, 25)], hist, TZ)
    assert n == 0
    assert out[0]["total_pred"] == pytest.approx(50.0)


# --------------------------- night-session bucket classification ---------------------------

def test_night_bucket_shifts_6h_across_weekday_boundaries():
    # Real 2026 calendar: 07-03=Fri, 07-04=Sat, 07-05=Sun, 07-06=Mon, 07-07=Tue.
    cases = [
        ("2026-07-04 02:00", "weekend"),  # Sat 02:00 -6h -> Fri 20:00 -> Fri -> weekend
        ("2026-07-07 02:00", "weekday"),  # Tue 02:00 -6h -> Mon 20:00 -> Mon -> weekday
        ("2026-07-05 02:00", "weekend"),  # Sun 02:00 -6h -> Sat 20:00 -> Sat -> weekend
        ("2026-07-06 02:00", "weekday"),  # Mon 02:00 -6h -> Sun 20:00 -> Sun -> weekday
        ("2026-07-03 23:30", "weekend"),  # Fri 23:30 -6h -> Fri 17:30 -> Fri -> weekend
    ]
    for ts_str, expected in cases:
        ts = pd.Timestamp(ts_str, tz=TZ)
        assert _night_bucket(ts) == expected, ts_str


# --------------------------- late_night_clamp: DOW-bucket awareness ---------------------------

def test_dow_aware_clamp_closes_weekday_hole_but_preserves_weekend():
    """Core fix: an aisekiya-like store closed on weekday deep-night, busy Fri/Sat.

    Old (all-days) clamp: the weekend actuals (30/32/28) inflate the combined cap to
    1.3*32=41.6, so a bogus weekday ML=25 sails through un-clamped (the proven bug:
    ay_chiba/ay_ueno weekday 02:00 ghost predictions). New (DOW-bucket) clamp: the
    weekday bucket sees its own all-zero history (n=5 >= CLAMP_MIN_NIGHTS_WEEKDAY) so
    its cap collapses to 0. The weekend bucket (n=3 >= CLAMP_MIN_NIGHTS_WEEKEND) keeps
    its own high cap and the weekend prediction is left untouched.
    """
    hist = _hist(
        [
            ("2026-06-27 02:00", 0, 0, 30),  # Sat -> weekend bucket (Fri-night session)
            ("2026-06-28 02:00", 0, 0, 32),  # Sun -> weekend bucket (Sat-night session)
            ("2026-06-29 02:00", 0, 0, 0),   # Mon -> weekday bucket
            ("2026-06-30 02:00", 0, 0, 0),   # Tue -> weekday bucket
            ("2026-07-01 02:00", 0, 0, 0),   # Wed -> weekday bucket
            ("2026-07-02 02:00", 0, 0, 0),   # Thu -> weekday bucket
            ("2026-07-03 02:00", 0, 0, 0),   # Fri -> weekday bucket
            ("2026-07-04 02:00", 0, 0, 28),  # Sat -> weekend bucket (Fri-night session)
        ]
    )
    weekday_point = _pt("2026-07-08 02:00", 15, 10)  # Wed 02:00, bogus ML total=25
    weekend_point = _pt("2026-07-11 02:00", 12, 8)   # Sat 02:00, real weekend total=20

    out, n = late_night_clamp([weekday_point, weekend_point], hist, TZ)
    assert n == 1
    assert out[0]["clamped"] is True
    assert out[0]["clamp_bucket"] == "weekday"
    assert out[0]["total_pred"] == pytest.approx(0.0)
    assert out[0]["men_pred"] == pytest.approx(0.0)
    assert out[0]["women_pred"] == pytest.approx(0.0)
    # Weekend slot: cap = 1.3*32 = 41.6, prediction (20) is under cap -> untouched.
    assert "clamped" not in out[1]
    assert out[1]["total_pred"] == pytest.approx(20.0)


def test_bucket_below_min_nights_falls_back_to_legacy_all_days_max():
    """A bucket with too little history (< its MIN_NIGHTS) must fall back to the
    legacy all-days max — never a stricter (bucket-only) cap, never skipped either.
    """
    hist = _hist(
        [
            ("2026-06-29 23:30", 0, 0, 6),   # Mon -> weekday bucket (n=1 so far)
            ("2026-06-30 23:30", 0, 0, 6),   # Tue -> weekday bucket (n=2 < MIN_NIGHTS_WEEKDAY=3)
            ("2026-06-27 23:30", 0, 0, 20),  # Sat -> weekend bucket
            ("2026-07-04 23:30", 0, 0, 20),  # Sat -> weekend bucket
        ]
    )
    point = _pt("2026-07-08 23:30", 25, 15)  # Wed 23:30 -> weekday bucket, ML total=40

    out, n = late_night_clamp([point], hist, TZ)
    assert n == 1
    # weekday bucket has only 2 nights (< 3) -> fall back to legacy all-days stat:
    # max=20 (from the two Sat rows), n=4 nights -> cap = 1.3*20 = 26.
    assert out[0]["clamp_bucket"] == "all_days"
    assert out[0]["total_pred"] == pytest.approx(26.0)
    assert out[0]["men_pred"] == pytest.approx(25 * 26.0 / 40.0)
    assert out[0]["women_pred"] == pytest.approx(15 * 26.0 / 40.0)


def test_clamp_dow_aware_off_switch_reverts_to_legacy_all_days(monkeypatch):
    """FORECAST_CLAMP_DOW_AWARE=0 must reproduce the exact legacy (pre-fix) behavior,
    including its bug: the weekend actuals inflate the weekday cap so the ghost
    prediction is NOT clamped. This documents the fallback path is byte-for-byte the
    old code path (see test_dow_aware_clamp_closes_weekday_hole_but_preserves_weekend
    for the fixed behavior with the flag left at its default "1").
    """
    monkeypatch.setenv("FORECAST_CLAMP_DOW_AWARE", "0")
    hist = _hist(
        [
            ("2026-06-27 02:00", 0, 0, 30),
            ("2026-06-28 02:00", 0, 0, 32),
            ("2026-06-29 02:00", 0, 0, 0),
            ("2026-06-30 02:00", 0, 0, 0),
            ("2026-07-01 02:00", 0, 0, 0),
            ("2026-07-02 02:00", 0, 0, 0),
            ("2026-07-03 02:00", 0, 0, 0),
            ("2026-07-04 02:00", 0, 0, 28),
        ]
    )
    weekday_point = _pt("2026-07-08 02:00", 15, 10)  # ML total=25

    out, n = late_night_clamp([weekday_point], hist, TZ)
    # Legacy (all-days) cap = 1.3 * max(30, 32, 0, 0, 0, 0, 0, 28) = 1.3*32 = 41.6 > 25.
    assert n == 0
    assert "clamped" not in out[0]
    assert out[0]["total_pred"] == pytest.approx(25.0)


def test_same_slot_stats_by_bucket_splits_weekday_and_weekend():
    hist = _hist(
        [
            ("2026-07-01 23:30", 0, 0, 10),  # Wed -> weekday
            ("2026-07-02 23:30", 0, 0, 8),   # Thu -> weekday
            ("2026-07-03 23:30", 0, 0, 6),   # Fri -> weekend (Fri-night session)
        ]
    )
    stats = same_slot_stats_by_bucket(hist, 15)
    assert stats[("weekday", 23, 30)] == (10.0, 2)
    assert stats[("weekend", 23, 30)] == (6.0, 1)


def test_clamp_exception_logs_warning_and_returns_input_unchanged(monkeypatch, caplog):
    def _boom(*_a, **_k):
        raise RuntimeError("boom-clamp")

    monkeypatch.setattr("oriental.ml.postprocess.same_slot_stats", _boom)
    hist = _hist([("2026-07-01 23:30", 0, 0, 10)])
    points = [_pt("2026-07-08 23:30", 25, 25)]
    with caplog.at_level(logging.WARNING):
        out, n = late_night_clamp(points, hist, TZ)
    assert n == 0
    assert out == points
    assert any("boom-clamp" in rec.message for rec in caplog.records)


# --------------------------- blend_with_baseline ---------------------------

def test_blend_basic_inverse_weight():
    hist = _hist([("2026-07-01 23:00", 10, 10, 20)])  # baseline 7 days before the point
    points = [_pt("2026-07-08 23:00", 40, 37)]
    out, n = blend_with_baseline(points, hist, TZ, w_ml=0.2)
    assert n == 1
    assert out[0]["men_pred"] == pytest.approx(0.2 * 40 + 0.8 * 10)  # 16.0
    assert out[0]["women_pred"] == pytest.approx(0.2 * 37 + 0.8 * 10)  # 15.4
    assert out[0]["total_pred"] == pytest.approx(31.4)  # total == men + women
    assert out[0]["blend_w_ml"] == 0.2


def test_blend_skips_missing_baseline_slot():
    hist = _hist([("2026-07-01 22:00", 10, 10, 20)])  # 22:00, not the 23:00 baseline slot
    points = [_pt("2026-07-08 23:00", 40, 37)]
    out, n = blend_with_baseline(points, hist, TZ, w_ml=0.2)
    assert n == 0
    assert out[0]["total_pred"] == pytest.approx(77.0)  # pure ML


def test_blend_pure_ml_when_weight_one():
    hist = _hist([("2026-07-01 23:00", 10, 10, 20)])
    points = [_pt("2026-07-08 23:00", 40, 37)]
    out, n = blend_with_baseline(points, hist, TZ, w_ml=1.0)
    assert n == 0
    assert out[0]["total_pred"] == pytest.approx(77.0)


def test_blend_extracts_7day_old_slot_from_8day_history():
    # 8 days of 23:00 rows; only the 7-days-earlier row is the baseline for the point.
    rows = [(f"2026-07-0{d} 23:00", d, d, 2 * d) for d in range(1, 9)]
    hist = _hist(rows)
    points = [_pt("2026-07-14 23:00", 100, 100)]  # baseline = 2026-07-07 (men=women=7)
    out, n = blend_with_baseline(points, hist, TZ, w_ml=0.0)  # pure baseline
    assert n == 1
    assert out[0]["men_pred"] == pytest.approx(7.0)
    assert out[0]["women_pred"] == pytest.approx(7.0)
    assert out[0]["total_pred"] == pytest.approx(14.0)


def test_blend_off_switch(monkeypatch):
    monkeypatch.setenv("FORECAST_BASELINE_BLEND", "0")
    hist = _hist([("2026-07-01 23:00", 10, 10, 20)])
    points = [_pt("2026-07-08 23:00", 40, 37)]
    out, n = blend_with_baseline(points, hist, TZ, w_ml=0.2)
    assert n == 0
    assert out[0]["total_pred"] == pytest.approx(77.0)


def test_blend_exception_logs_warning_and_returns_input_unchanged(monkeypatch, caplog):
    def _boom(*_a, **_k):
        raise RuntimeError("boom-blend")

    monkeypatch.setattr("oriental.ml.postprocess.actual_slot_map", _boom)
    hist = _hist([("2026-07-01 23:00", 10, 10, 20)])
    points = [_pt("2026-07-08 23:00", 40, 37)]
    with caplog.at_level(logging.WARNING):
        out, n = blend_with_baseline(points, hist, TZ, w_ml=0.2)
    assert n == 0
    assert out == points
    assert any("boom-blend" in rec.message for rec in caplog.records)


# --------------------------- blend + clamp together ---------------------------

def test_blend_then_clamp_order_gangnam():
    # gangnam-like store: recent nights actual 0 after 00:30, model predicting 50.
    rows = [(f"2026-07-0{d} 00:30", 0, 0, 0) for d in range(1, 8)]
    hist = _hist(rows)
    points = [_pt("2026-07-08 00:30", 25, 25)]  # ML says 50

    blended, nb = blend_with_baseline(points, hist, TZ, w_ml=0.2)
    assert nb == 1
    assert blended[0]["total_pred"] == pytest.approx(10.0)  # 0.2*50 + 0.8*0

    clamped, nc = late_night_clamp(blended, hist, TZ)  # cap = 1.3*0 = 0
    assert nc == 1
    assert clamped[0]["total_pred"] == pytest.approx(0.0)  # clamp bounds the final output


def test_winner_high_weight_barely_changes():
    rows = [(f"2026-07-0{d} 23:00", 18, 18, 36) for d in range(1, 8)]
    hist = _hist(rows)
    points = [_pt("2026-07-08 23:00", 20, 20)]  # ML 40

    blended, nb = blend_with_baseline(points, hist, TZ, w_ml=0.9)
    assert blended[0]["men_pred"] == pytest.approx(19.8)  # 0.9*20 + 0.1*18
    assert blended[0]["total_pred"] == pytest.approx(39.6)

    clamped, nc = late_night_clamp(blended, hist, TZ)  # cap = 1.3*36 = 46.8 > 39.6
    assert nc == 0
    assert clamped[0]["total_pred"] == pytest.approx(39.6)


# --------------------------- helper functions ---------------------------

def test_same_slot_stats_counts_nights_and_max():
    hist = _hist(
        [
            ("2026-07-01 23:30", 0, 0, 10),
            ("2026-07-02 23:30", 0, 0, 4),
            ("2026-07-03 23:30", 0, 0, 7),
        ]
    )
    stats = same_slot_stats(hist, 15)
    assert stats[(23, 30)] == (10.0, 3)


def test_actual_slot_map_averages_duplicate_slots():
    hist = _hist(
        [
            ("2026-07-01 23:00", 4, 6, 10),
            ("2026-07-01 23:05", 6, 4, 10),  # same 15-min slot -> averaged
        ]
    )
    m = actual_slot_map(hist, TZ, 15)
    key = pd.Timestamp("2026-07-01 23:00", tz=TZ)
    assert m[key]["total"] == pytest.approx(10.0)
    assert m[key]["men"] == pytest.approx(5.0)
    assert m[key]["women"] == pytest.approx(5.0)


# --------------------------- ForecastService wiring ---------------------------

class _StubModel:
    def predict(self, features):
        n = len(features)
        return np.zeros(n, dtype=float), np.zeros(n, dtype=float)


class _StubBundle:
    def __init__(self):
        self.model = _StubModel()
        self.metadata = {}
        self.loaded_at_unix = 0.0


class _StubRegistry:
    def get_bundle(self, store_id):
        return _StubBundle()


class _OneRecordProvider:
    def __init__(self):
        self.logger = logging.getLogger("test")

    def get_records(self, store_id, **_kwargs):
        return [{"ts": "2024-11-01T00:00:00Z", "men": 1, "women": 2, "total": 3}]


def test_service_emits_postprocess_fields_and_weight_fallback():
    from oriental.ml.forecast_service import ForecastService

    service = ForecastService(
        provider=_OneRecordProvider(),
        timezone=TZ,
        model_registry=_StubRegistry(),
        history_days=8,
        history_limit=100,
        storage_url="",  # no storage configured -> graceful w_ml fallback to 1.0
        storage_key="",
    )
    res = service.forecast_next_hour(store_id="ol_test", freq_min=15)
    assert res["ok"] is True
    assert res["blend_w_ml"] == 1.0
    assert res["blended_slots"] == 0
    assert "clamped_slots" in res


def test_service_blend_weight_lookup_and_toggle(monkeypatch):
    from oriental.ml.forecast_service import ForecastService
    import time as _time

    service = ForecastService(
        provider=_OneRecordProvider(),
        timezone=TZ,
        model_registry=_StubRegistry(),
        storage_url="",
        storage_key="",
    )
    # Pre-seed the in-process cache (bypass network) and verify per-store lookup.
    service._blend_weights = {"ol_gangnam": 0.2}
    service._blend_weights_at = _time.time()
    assert service._blend_weight_for("ol_gangnam") == 0.2
    assert service._blend_weight_for("ol_unknown") == 1.0  # default fallback

    monkeypatch.setenv("FORECAST_BASELINE_BLEND", "0")
    assert service._blend_weight_for("ol_gangnam") == 1.0  # blend disabled -> pure ML


def test_history_window_covers_blend_baseline_requirement():
    """回帰ガード: from_app の履歴取得上限は「8日分の5分毎データ(=960行)」を必ず賄うこと。

    旧上限600行は最新5夜に黙って切り詰められ、ベースライン・ブレンドの
    「7日前・同一スロット実測」が常に窓の外＝全店で空振りするバグだった
    (2026-07-09 に gangnam 実データ 960行/8日 で確認)。
    """
    import inspect
    from oriental.ml import forecast_service as fs

    src = inspect.getsource(fs.ForecastService.from_app)
    # from_app 内の履歴上限が 8日×120行/夜=960 以上であることをソースレベルで担保する。
    import re

    m = re.search(r"history_limit\s*=\s*min\(cfg\.max_range_limit,\s*(\d+)\)", src)
    assert m, "from_app の history_limit 定義が見つからない(リファクタ時はこのテストを更新)"
    assert int(m.group(1)) >= 8 * 120, (
        f"history_limit 上限 {m.group(1)} が 8日分(960行) 未満: ブレンドの7日前参照が壊れる"
    )
