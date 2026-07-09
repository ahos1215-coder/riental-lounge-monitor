"""Unit tests for the closed-loop feedback in scripts/score_forecasts.py:
inverse-error blend-weight formula, per-store aggregation, and the
baseline-loss exit-code behavior (all mocked / no network).
"""

import json
from datetime import datetime, timedelta

import pytest

import scripts.score_forecasts as sf


# --------------------------- blend_weight formula ---------------------------

def test_blend_weight_winner_clamped_high():
    # ML strongly beats baseline, >=4 nights -> clamps to 0.9
    assert sf.blend_weight(2.0, 38.0, 7) == 0.9


def test_blend_weight_gangnam_low():
    # gangnam-like: ML much worse than baseline -> low w_ml (mostly baseline)
    expected = 6.97 / (28.4 + 6.97)
    assert sf.blend_weight(28.4, 6.97, 7) == pytest.approx(expected, abs=1e-9)
    assert 0.15 <= sf.blend_weight(28.4, 6.97, 7) <= 0.3


def test_blend_weight_lower_clamp():
    assert sf.blend_weight(100.0, 1.0, 7) == 0.15


def test_blend_weight_shrinks_toward_half_when_few_nights():
    # n=0 -> fully shrunk to 0.5
    assert sf.blend_weight(2.0, 38.0, 0) == 0.5
    # n=1 -> (1*w + 3*0.5)/4 with w=0.95
    raw = 38.0 / 40.0
    assert sf.blend_weight(2.0, 38.0, 1) == pytest.approx((1 * raw + 3 * 0.5) / 4)
    # n=2
    assert sf.blend_weight(2.0, 38.0, 2) == pytest.approx((2 * raw + 2 * 0.5) / 4)
    # n>=4 -> no shrink (then clamp)
    assert sf.blend_weight(2.0, 38.0, 4) == 0.9


def test_blend_weight_zero_errors_neutral():
    assert sf.blend_weight(0.0, 0.0, 7) == 0.5


# --------------------------- compute_blend_weights ---------------------------

def test_compute_blend_weights_aggregates_and_maps_store_ids(monkeypatch):
    scores = {
        "20260707": {
            "per_store": {
                "gangnam": {"live_mae": 28.0, "live_baseline_mae": 7.0},
                "umeda_ag": {"live_mae": 3.0, "live_baseline_mae": 9.0},
                "ay_ikebukuro": {"live_mae": 11.0, "live_baseline_mae": 4.0},
            }
        },
        "20260706": {
            "per_store": {
                "gangnam": {"live_mae": 30.0, "live_baseline_mae": 7.0},
            }
        },
    }

    def fake_get(bucket, path, url, key):
        for d, doc in scores.items():
            if path == f"accuracy/scores/{d}.json":
                return json.dumps(doc).encode()
        return None

    monkeypatch.setattr(sf, "_storage_get", fake_get)
    weights = sf.compute_blend_weights("ml-models", "http://x", "k", ["20260707", "20260706"])

    # keyed by serving store_id (ol_ prefix for oriental, ay_ passthrough)
    assert set(weights) == {"ol_gangnam", "ol_umeda_ag", "ay_ikebukuro"}

    # gangnam: 2 nights, mean ml=29, base=7 -> w_raw=7/36, shrink n=2
    w_raw = 7.0 / 36.0
    exp_gangnam = round((2 * w_raw + 2 * 0.5) / 4, 4)
    assert weights["ol_gangnam"] == exp_gangnam

    # umeda_ag: 1 night, ml=3, base=9 -> w_raw=0.75, shrink n=1
    exp_umeda = round((1 * 0.75 + 3 * 0.5) / 4, 4)
    assert weights["ol_umeda_ag"] == exp_umeda


def test_compute_blend_weights_empty_when_no_scores(monkeypatch):
    monkeypatch.setattr(sf, "_storage_get", lambda *a, **k: None)
    assert sf.compute_blend_weights("b", "u", "k", ["20260707"]) == {}


# --------------------------- main() exit-code behavior ---------------------------

def _wire_main(monkeypatch, *, now_total, prev_total):
    """Set up a single-store scoring run with mocked storage/actuals.
    Returns nothing; the caller invokes sf.main() and checks the return code.
    """
    monkeypatch.setattr(sf, "_load_env", lambda: None)
    monkeypatch.setenv("SUPABASE_URL", "http://x")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "k")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    night_date = (datetime.now(sf.JST) - timedelta(days=1)).strftime("%Y%m%d")
    base = datetime.strptime(night_date, "%Y%m%d").replace(tzinfo=sf.JST)
    slot = base.replace(hour=23, minute=0, second=0, microsecond=0)
    snapshot = {"by_slug": {"shibuya": [{"ts": slot.isoformat(), "total_pred": 50.0}]}}

    def fake_get(bucket, path, url, key):
        if path.startswith("accuracy/snapshots/"):
            return json.dumps(snapshot).encode()
        return None

    monkeypatch.setattr(sf, "_storage_get", fake_get)
    monkeypatch.setattr(sf, "_storage_put", lambda *a, **k: None)
    monkeypatch.setattr(sf, "_alert", lambda msg: None)

    now_rows = [{"ts": slot.isoformat(), "total": float(now_total)}]
    prev_rows = [{"ts": (slot - timedelta(days=7)).isoformat(), "total": float(prev_total)}]
    calls = {"i": 0}

    def fake_actuals(url, key, store_id, s_iso, e_iso):
        calls["i"] += 1
        return now_rows if calls["i"] == 1 else prev_rows

    monkeypatch.setattr(sf, "_fetch_actuals", fake_actuals)


def test_main_returns_1_when_ml_loses_to_baseline(monkeypatch):
    monkeypatch.delenv("ACCURACY_FAIL_ON_BASELINE_LOSS", raising=False)
    # actual 10; ML pred 50 (err 40); baseline last-week 12 (err 2) -> ML loses
    _wire_main(monkeypatch, now_total=10, prev_total=12)
    assert sf.main() == 1


def test_main_returns_0_when_ml_beats_baseline(monkeypatch):
    monkeypatch.delenv("ACCURACY_FAIL_ON_BASELINE_LOSS", raising=False)
    # actual 48; ML pred 50 (err 2); baseline last-week 10 (err 38) -> ML wins
    _wire_main(monkeypatch, now_total=48, prev_total=10)
    assert sf.main() == 0


def test_main_off_switch_suppresses_failure(monkeypatch):
    monkeypatch.setenv("ACCURACY_FAIL_ON_BASELINE_LOSS", "0")
    _wire_main(monkeypatch, now_total=10, prev_total=12)  # ML loses
    assert sf.main() == 0  # but failure suppressed by off-switch
