"""Unit tests for the train_ml_model.py champion/challenger gate, active-store
allow-list + stale-store guard, coverage visibility, HPO-param reuse, and the
parameterized recency-weighting knobs.

All tests are pure/offline: synthetic DataFrames and dicts only, no Supabase /
network calls, no real model training.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.train_ml_model import (
    TrainingConfig,
    _carry_forward_store,
    _coverage_stats,
    _filter_allowed_stores,
    _filter_store_models_to_allowlist,
    _gate_decision,
    _is_stale_store,
    _reused_hpo_params,
    _sample_weights,
)


def _make_cfg(**overrides) -> TrainingConfig:
    base = dict(
        supabase_url="https://example.supabase.co",
        supabase_service_key="dummy-key",
        bucket="ml-models",
        prefix="forecast/latest",
        schema_version="v7",
        timezone="Asia/Tokyo",
        train_days=180,
        train_limit=1_000_000,
        store_id=None,
        sample_weight_peak=1.8,
        sample_weight_rain=1.8,
        optuna_trials=30,
        optuna_enabled=True,
        objective="regression",
        optuna_max_rows=0,
        gate_max_regression_pct=20.0,
        stale_store_days=7.0,
        recency_halflife_days=90.0,
        recency_floor=0.5,
    )
    base.update(overrides)
    return TrainingConfig(**base)


# ---------------------------------------------------------------------------
# Champion/challenger gate
# ---------------------------------------------------------------------------

def test_gate_replaces_when_better():
    decision, reason = _gate_decision(new_mae=8.0, old_mae=10.0, max_regression_pct=20.0)
    assert decision == "replaced"
    assert "regression_pct" in reason


def test_gate_replaces_when_within_threshold():
    # 10% worse, threshold is 20% -> still replace
    decision, reason = _gate_decision(new_mae=11.0, old_mae=10.0, max_regression_pct=20.0)
    assert decision == "replaced"


def test_gate_skips_when_worse_than_threshold():
    # 30% worse than old_mae, threshold 20% -> must skip
    decision, reason = _gate_decision(new_mae=13.0, old_mae=10.0, max_regression_pct=20.0)
    assert decision == "skipped"
    assert "regression_pct=30.0" in reason


def test_gate_boundary_exactly_at_threshold_is_not_a_regression():
    # exactly +20% should NOT trip the ">" comparison
    decision, _ = _gate_decision(new_mae=12.0, old_mae=10.0, max_regression_pct=20.0)
    assert decision == "replaced"


def test_gate_replaces_on_missing_old_metrics_first_run():
    decision, reason = _gate_decision(new_mae=9.0, old_mae=None, max_regression_pct=20.0)
    assert decision == "replaced"
    assert reason == "no_prior_metrics"


def test_gate_replaces_on_missing_new_metrics():
    decision, reason = _gate_decision(new_mae=None, old_mae=10.0, max_regression_pct=20.0)
    assert decision == "replaced"
    assert reason == "no_prior_metrics"


def test_gate_replaces_when_old_mae_is_zero_or_negative():
    # can't compute a meaningful regression pct against 0 -> upload gracefully
    decision, _ = _gate_decision(new_mae=5.0, old_mae=0.0, max_regression_pct=20.0)
    assert decision == "replaced"


# ---------------------------------------------------------------------------
# Stale-store guard
# ---------------------------------------------------------------------------

def test_is_stale_store_true_when_old():
    now = pd.Timestamp("2026-07-09", tz="Asia/Tokyo")
    last = pd.Timestamp("2026-05-11", tz="Asia/Tokyo")  # ~59 days old
    assert _is_stale_store(last, now, stale_days=7.0) is True


def test_is_stale_store_false_when_recent():
    now = pd.Timestamp("2026-07-09", tz="Asia/Tokyo")
    last = pd.Timestamp("2026-07-08", tz="Asia/Tokyo")  # 1 day old
    assert _is_stale_store(last, now, stale_days=7.0) is False


def test_is_stale_store_boundary_exactly_at_threshold_is_not_stale():
    now = pd.Timestamp("2026-07-09T00:00:00", tz="Asia/Tokyo")
    last = pd.Timestamp("2026-07-02T00:00:00", tz="Asia/Tokyo")  # exactly 7.0 days
    assert _is_stale_store(last, now, stale_days=7.0) is False


# ---------------------------------------------------------------------------
# Active-store allow-list intersection
# ---------------------------------------------------------------------------

def test_filter_allowed_stores_splits_correctly():
    allow_list = {"ol_shibuya", "ol_ebisu", "ay_ueno"}
    found = ["ol_shibuya", "ol_sapporo_ag", "ay_ueno", "unknown_store"]
    allowed, rejected = _filter_allowed_stores(found, allow_list)
    assert allowed == ["ol_shibuya", "ay_ueno"]
    assert rejected == ["ol_sapporo_ag", "unknown_store"]


def test_filter_allowed_stores_all_allowed():
    allow_list = {"ol_shibuya", "ol_ebisu"}
    allowed, rejected = _filter_allowed_stores(["ol_shibuya", "ol_ebisu"], allow_list)
    assert allowed == ["ol_shibuya", "ol_ebisu"]
    assert rejected == []


def test_filter_allowed_stores_none_allowed():
    allow_list = {"ol_shibuya"}
    allowed, rejected = _filter_allowed_stores(["ol_sapporo_ag", "ay_niigata"], allow_list)
    assert allowed == []
    assert rejected == ["ol_sapporo_ag", "ay_niigata"]


# ---------------------------------------------------------------------------
# HPO params reuse (weekly Optuna -> daily fixed-param run)
# ---------------------------------------------------------------------------

def test_reused_hpo_params_returns_existing_params():
    existing_metrics = {"ol_shibuya": {"overall": {"total_mae": 5.0}, "hpo_params": {"max_depth": 6}}}
    params = _reused_hpo_params(existing_metrics, "ol_shibuya")
    assert params == {"max_depth": 6}


def test_reused_hpo_params_missing_store_returns_empty():
    existing_metrics = {"ol_ebisu": {"hpo_params": {"max_depth": 6}}}
    assert _reused_hpo_params(existing_metrics, "ol_shibuya") == {}


def test_reused_hpo_params_missing_key_returns_empty():
    existing_metrics = {"ol_shibuya": {"overall": {"total_mae": 5.0}}}
    assert _reused_hpo_params(existing_metrics, "ol_shibuya") == {}


def test_reused_hpo_params_empty_dict_returns_empty():
    existing_metrics = {"ol_shibuya": {"hpo_params": {}}}
    assert _reused_hpo_params(existing_metrics, "ol_shibuya") == {}


def test_reused_hpo_params_non_dict_entry_returns_empty():
    existing_metrics = {"ol_shibuya": "not-a-dict"}
    assert _reused_hpo_params(existing_metrics, "ol_shibuya") == {}


# ---------------------------------------------------------------------------
# Carry-forward of skipped/untouched stores
# ---------------------------------------------------------------------------

def test_carry_forward_store_copies_model_and_metrics():
    existing_store_models = {"ol_sapporo_ag": {"model_men": "model_ol_sapporo_ag_men.txt"}}
    existing_metrics = {"ol_sapporo_ag": {"overall": {"total_mae": 4.2}}}
    store_models: dict = {}
    all_metrics: dict = {}
    gate_decisions: list = []

    _carry_forward_store(
        "ol_sapporo_ag",
        "stale_store last=2026-05-11",
        existing_store_models=existing_store_models,
        existing_metrics=existing_metrics,
        store_models=store_models,
        all_metrics=all_metrics,
        gate_decisions=gate_decisions,
    )

    assert store_models["ol_sapporo_ag"] == {"model_men": "model_ol_sapporo_ag_men.txt"}
    assert all_metrics["ol_sapporo_ag"]["gate_skipped"] is True
    assert all_metrics["ol_sapporo_ag"]["gate_reason"] == "stale_store last=2026-05-11"
    assert all_metrics["ol_sapporo_ag"]["overall"]["total_mae"] == 4.2
    assert gate_decisions == [
        {"store_id": "ol_sapporo_ag", "decision": "skipped", "reason": "stale_store last=2026-05-11"}
    ]


def test_carry_forward_store_noop_when_nothing_existing():
    store_models: dict = {}
    all_metrics: dict = {}
    gate_decisions: list = []
    _carry_forward_store(
        "unknown_new_store",
        "not_in_allowlist",
        existing_store_models={},
        existing_metrics={},
        store_models=store_models,
        all_metrics=all_metrics,
        gate_decisions=gate_decisions,
    )
    assert store_models == {}
    assert all_metrics == {}
    assert gate_decisions == [{"store_id": "unknown_new_store", "decision": "skipped", "reason": "not_in_allowlist"}]


# ---------------------------------------------------------------------------
# Allow-list convergence filter (fix #16a, 2026-07-18 Fable audit)
#
# _carry_forward_store (exercised above) unconditionally copies whatever
# existing_store_models/existing_metrics had for a store_id into store_models/
# all_metrics, REGARDLESS of why it was skipped -- including "not_in_allowlist".
# The main() "completeness" loop does the same for any existing_store_models
# entry this run never touched at all. Both are correct for stores still in
# ALL_STORE_IDS that transiently produced no data, but wrong for a store
# PERMANENTLY removed from ALL_STORE_IDS (closed, e.g. sapporo_ag/ay_niigata):
# such a store never appears in the freshly-fetched training data again, so it
# is never explicitly rejected -- its last-deployed entry just keeps getting
# carried forward forever. _filter_store_models_to_allowlist is the final
# convergence filter applied once, right before metadata.json is built, that
# guarantees this can't happen regardless of which upstream path added the
# stale entry.
# ---------------------------------------------------------------------------


def test_filter_store_models_to_allowlist_drops_closed_stores():
    allow_list = {"ol_shibuya", "ay_ueno"}
    store_models = {
        "ol_shibuya": {"model_men": "a"},
        "ol_sapporo_ag": {"model_men": "b"},  # closed 2026-07-11
        "ay_ueno": {"model_men": "c"},
        "ay_niigata": {"model_men": "d"},  # closed
    }
    all_metrics = {
        "ol_shibuya": {"overall": {"total_mae": 5.0}},
        "ol_sapporo_ag": {"overall": {"total_mae": 9.0}},
        "ay_ueno": {"overall": {"total_mae": 3.0}},
    }

    filtered_models, filtered_metrics, dropped = _filter_store_models_to_allowlist(
        store_models, all_metrics, allow_list
    )

    assert filtered_models == {"ol_shibuya": {"model_men": "a"}, "ay_ueno": {"model_men": "c"}}
    assert filtered_metrics == {
        "ol_shibuya": {"overall": {"total_mae": 5.0}},
        "ay_ueno": {"overall": {"total_mae": 3.0}},
    }
    assert dropped == ["ay_niigata", "ol_sapporo_ag"]


def test_filter_store_models_to_allowlist_noop_when_all_allowed():
    allow_list = {"ol_shibuya", "ol_ebisu"}
    store_models = {"ol_shibuya": {"a": 1}, "ol_ebisu": {"b": 2}}
    all_metrics = {"ol_shibuya": {"c": 3}}

    filtered_models, filtered_metrics, dropped = _filter_store_models_to_allowlist(
        store_models, all_metrics, allow_list
    )

    assert filtered_models == store_models
    assert filtered_metrics == all_metrics
    assert dropped == []


def test_filter_store_models_to_allowlist_metrics_key_absent_from_store_models_is_also_dropped():
    # all_metrics can (in principle) carry a store_id that store_models doesn't --
    # the filter must still drop it from all_metrics if it's off the allow-list,
    # independently of what store_models contains.
    allow_list = {"ol_shibuya"}
    store_models = {"ol_shibuya": {"a": 1}}
    all_metrics = {"ol_shibuya": {"a": 1}, "ol_sapporo_ag": {"b": 2}}

    _, filtered_metrics, _ = _filter_store_models_to_allowlist(store_models, all_metrics, allow_list)

    assert filtered_metrics == {"ol_shibuya": {"a": 1}}


def test_filter_store_models_to_allowlist_handles_empty_inputs():
    filtered_models, filtered_metrics, dropped = _filter_store_models_to_allowlist({}, {}, {"ol_shibuya"})
    assert filtered_models == {}
    assert filtered_metrics == {}
    assert dropped == []


def test_carry_forward_then_allowlist_filter_converges_to_42():
    """End-to-end (pure/offline) regression for bug #16a: simulate the exact
    scenario that used to keep closed stores alive forever -- a store rejected
    this run for being off the allow-list still gets carried forward by
    _carry_forward_store, but the final allow-list filter must drop it again."""
    allow_list = {"ol_shibuya"}
    existing_store_models = {
        "ol_shibuya": {"model_men": "current"},
        "ol_sapporo_ag": {"model_men": "stale-forever"},
    }
    existing_metrics = {
        "ol_shibuya": {"overall": {"total_mae": 5.0}},
        "ol_sapporo_ag": {"overall": {"total_mae": 12.0}},
    }
    store_models: dict = {"ol_shibuya": {"model_men": "current"}}
    all_metrics: dict = {"ol_shibuya": {"overall": {"total_mae": 5.0}}}
    gate_decisions: list = []

    # Simulates main()'s rejected-store loop: `ol_sapporo_ag` was found in
    # `stores_in_data` on some earlier run/import and rejected as not-in-allowlist,
    # but _carry_forward_store copies its old entry forward anyway (the pre-existing,
    # not-fixed-here behavior).
    _carry_forward_store(
        "ol_sapporo_ag",
        "not_in_allowlist",
        existing_store_models=existing_store_models,
        existing_metrics=existing_metrics,
        store_models=store_models,
        all_metrics=all_metrics,
        gate_decisions=gate_decisions,
    )
    assert "ol_sapporo_ag" in store_models  # confirms the pre-fix contamination happens

    filtered_models, filtered_metrics, dropped = _filter_store_models_to_allowlist(
        store_models, all_metrics, allow_list
    )
    assert filtered_models == {"ol_shibuya": {"model_men": "current"}}
    assert filtered_metrics == {"ol_shibuya": {"overall": {"total_mae": 5.0}}}
    assert dropped == ["ol_sapporo_ag"]


# ---------------------------------------------------------------------------
# Coverage visibility
# ---------------------------------------------------------------------------

def test_coverage_stats_detects_row_limit_hit():
    ts = pd.date_range("2026-06-01", periods=10, freq="D", tz="Asia/Tokyo")
    df = pd.DataFrame({"ts": ts})
    stats = _coverage_stats(df, requested_days=180, train_limit=10, rows_fetched=10)
    assert stats["requested_days"] == 180
    assert stats["total_rows"] == 10
    assert stats["row_limit_hit"] is True
    assert stats["effective_days"] == pytest.approx(9.0, abs=0.01)


def test_coverage_stats_no_row_limit_hit_when_below_limit():
    ts = pd.date_range("2026-06-01", periods=5, freq="D", tz="Asia/Tokyo")
    df = pd.DataFrame({"ts": ts})
    stats = _coverage_stats(df, requested_days=180, train_limit=1_000_000, rows_fetched=5)
    assert stats["row_limit_hit"] is False
    assert stats["effective_days"] == pytest.approx(4.0, abs=0.01)


def test_coverage_stats_handles_empty_df():
    df = pd.DataFrame({"ts": pd.Series([], dtype="datetime64[ns, Asia/Tokyo]")})
    stats = _coverage_stats(df, requested_days=180, train_limit=1000, rows_fetched=0)
    assert stats["effective_days"] == 0.0
    assert stats["oldest_ts"] is None
    assert stats["newest_ts"] is None
    assert stats["row_limit_hit"] is False


# ---------------------------------------------------------------------------
# Recency-weighting knobs (parameterized half-life / floor)
# ---------------------------------------------------------------------------

def _synthetic_weight_df(days_ago_values) -> pd.DataFrame:
    max_ts = pd.Timestamp("2026-07-09", tz="Asia/Tokyo")
    ts = [max_ts - pd.Timedelta(days=d) for d in days_ago_values]
    n = len(days_ago_values)
    return pd.DataFrame({
        "ts": ts,
        "hour": [10] * n,
        "dow": [1] * n,  # Tuesday: not in peak dow set
        "is_pre_holiday": [0] * n,
        "is_rainy": [0] * n,
    })


def test_sample_weights_default_matches_legacy_hardcoded_formula():
    # Defaults (halflife=90, floor=0.5) must reproduce the old hardcoded
    # 0.5 + 0.5*exp(-days_ago/90) exactly (no behavior change out of the box).
    cfg = _make_cfg(recency_halflife_days=90.0, recency_floor=0.5)
    df = _synthetic_weight_df([0, 30, 90, 180])
    weights = _sample_weights(df, cfg)
    expected = 0.5 + 0.5 * np.exp(-np.array([0, 30, 90, 180]) / 90.0)
    np.testing.assert_allclose(weights, expected, rtol=1e-9)


def test_sample_weights_custom_halflife_and_floor():
    cfg = _make_cfg(recency_halflife_days=45.0, recency_floor=0.25)
    df = _synthetic_weight_df([0, 45, 90])
    weights = _sample_weights(df, cfg)
    expected = 0.25 + 0.75 * np.exp(-np.array([0, 45, 90]) / 45.0)
    np.testing.assert_allclose(weights, expected, rtol=1e-9)
    # newest row always weighs 1.0 regardless of floor/halflife
    assert weights[0] == pytest.approx(1.0)
    # a tighter half-life decays faster than the legacy 90-day one at the same age
    legacy_cfg = _make_cfg(recency_halflife_days=90.0, recency_floor=0.5)
    legacy_weights = _sample_weights(df, legacy_cfg)
    assert weights[-1] < legacy_weights[-1]


def test_sample_weights_floor_is_the_asymptote():
    cfg = _make_cfg(recency_halflife_days=10.0, recency_floor=0.25)
    df = _synthetic_weight_df([0, 10_000])  # effectively "infinitely" old
    weights = _sample_weights(df, cfg)
    assert weights[-1] == pytest.approx(0.25, abs=1e-6)


# ---------------------------------------------------------------------------
# TrainingConfig.from_env picks up the new knobs (with sensible defaults)
# ---------------------------------------------------------------------------

def test_training_config_from_env_defaults(monkeypatch):
    for name in (
        "ML_GATE_MAX_REGRESSION_PCT", "ML_STALE_STORE_DAYS",
        "ML_RECENCY_HALFLIFE_DAYS", "ML_RECENCY_FLOOR",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "dummy-key")
    monkeypatch.setenv("FORECAST_MODEL_SCHEMA_VERSION", "v7")

    cfg = TrainingConfig.from_env()
    assert cfg.gate_max_regression_pct == 20.0
    assert cfg.stale_store_days == 7.0
    assert cfg.recency_halflife_days == 90.0
    assert cfg.recency_floor == 0.5
    cfg.validate()  # must not raise


def test_training_config_from_env_overrides(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "dummy-key")
    monkeypatch.setenv("FORECAST_MODEL_SCHEMA_VERSION", "v7")
    monkeypatch.setenv("ML_GATE_MAX_REGRESSION_PCT", "15")
    monkeypatch.setenv("ML_STALE_STORE_DAYS", "3")
    monkeypatch.setenv("ML_RECENCY_HALFLIFE_DAYS", "45")
    monkeypatch.setenv("ML_RECENCY_FLOOR", "0.25")

    cfg = TrainingConfig.from_env()
    assert cfg.gate_max_regression_pct == 15.0
    assert cfg.stale_store_days == 3.0
    assert cfg.recency_halflife_days == 45.0
    assert cfg.recency_floor == 0.25
    cfg.validate()


@pytest.mark.parametrize(
    "overrides",
    [
        {"gate_max_regression_pct": -1.0},
        {"stale_store_days": 0.0},
        {"recency_halflife_days": 0.0},
        {"recency_floor": 1.5},
        {"recency_floor": -0.1},
    ],
)
def test_training_config_validate_rejects_bad_new_knobs(overrides):
    cfg = _make_cfg(**overrides)
    with pytest.raises(SystemExit):
        cfg.validate()
