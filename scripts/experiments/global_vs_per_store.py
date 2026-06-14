"""Offline A/B experiment: ONE pooled "global" model vs many per-store models.

Answers the owner's question — does a single LightGBM trained on ALL stores
(with store_id as a feature) match or beat the current 1-model-per-store setup,
and does either actually beat the trivial "same weekday + same slot last week"
baseline?

Why this exists
---------------
- Per-store models each learn from only ~3k–19k rows; the literature (M5,
  Montero-Manso & Hyndman, the VN2-2026 winner) finds a single pooled model with
  a series id often matches or beats per-series models on many short related
  series, because it pools data and regularises quiet/small stores. store_id is
  passed as a categorical feature, so the global model can still learn each
  store's own level/shape (it does NOT average stores together).
- This is a READ-ONLY experiment. It trains throwaway models in memory, writes
  NOTHING to Supabase Storage, and does not touch production models.

How to read the result
----------------------
For every store it reports holdout total MAE for: per-store model, global model,
and seasonal-naive baseline (lower = better). The summary says how many stores
the global model wins/ties/loses vs per-store, and how many of each beat the
baseline. Run it AFTER the recency fix (ts.desc + raised ML_TRAIN_LIMIT) so the
data is recent; otherwise you are comparing models on stale data.

Usage
-----
    python scripts/experiments/global_vs_per_store.py
    python scripts/experiments/global_vs_per_store.py --days 180 --limit 1000000
    python scripts/experiments/global_vs_per_store.py --json out.json

Requires SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY in .env / .env.local.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests
from dotenv import load_dotenv

try:
    import lightgbm as lgb
except ImportError:  # pragma: no cover
    print("lightgbm is required: pip install -r requirements.txt", file=sys.stderr)
    raise

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from oriental.ml.preprocess import FEATURE_COLUMNS, prepare_dataframe

TEST_RATIO = 0.2
MIN_ROWS_PER_STORE = 200
LGB_PARAMS: dict[str, Any] = {
    "n_estimators": 300,
    "max_depth": 4,
    "learning_rate": 0.1,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "objective": "regression",
    "metric": "mae",
    "verbosity": -1,
}


def _load_env() -> None:
    for name in (".env", ".env.local"):
        p = REPO_ROOT / name
        if p.is_file():
            load_dotenv(p, override=(name == ".env.local"))


def _fetch_rows(days: int, limit: int) -> list[dict[str, Any]]:
    url = (os.getenv("SUPABASE_URL") or "").rstrip("/")
    key = (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or os.getenv("SUPABASE_SERVICE_KEY")
        or ""
    )
    if not url or not key:
        raise SystemExit("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")
    endpoint = f"{url}/rest/v1/logs"
    end_ts = datetime.now(timezone.utc)
    start_ts = end_ts - timedelta(days=max(1, days))
    page = 1000
    offset = 0
    rows: list[dict[str, Any]] = []
    session = requests.Session()
    while len(rows) < limit:
        params = [
            ("select", "store_id,ts,men,women,total,weather_code,temp_c,precip_mm"),
            ("order", "ts.desc"),  # newest-first, like the fixed training fetch
            ("limit", str(page)),
            ("offset", str(offset)),
            ("ts", f"gte.{start_ts.isoformat()}"),
            ("ts", f"lte.{end_ts.isoformat()}"),
            ("men", "not.is.null"),
            ("women", "not.is.null"),
        ]
        headers = {"apikey": key, "Authorization": f"Bearer {key}", "Accept": "application/json"}
        resp = session.get(endpoint, params=params, headers=headers, timeout=30)
        if not resp.ok:
            raise SystemExit(f"supabase fetch failed: {resp.status_code}")
        chunk = [r for r in resp.json() if isinstance(r, dict)]
        rows.extend(chunk)
        print(f"[global-ab][fetch] {len(rows)}")
        if len(chunk) < page:
            break
        offset += page
    return rows[:limit]


def _time_split(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    split = int(len(df) * (1.0 - TEST_RATIO))
    split = max(1, min(split, len(df) - 1))
    return df.iloc[:split].copy(), df.iloc[split:].copy()


def _fit(train: pd.DataFrame, target: str, features: list[str], categorical: list[str] | None = None) -> lgb.LGBMRegressor:
    model = lgb.LGBMRegressor(**LGB_PARAMS)
    fit_kw: dict[str, Any] = {}
    if categorical:
        fit_kw["categorical_feature"] = categorical
    model.fit(train[features], train[target].astype(float), **fit_kw)
    return model


def _total_mae(test: pd.DataFrame, pred_men: np.ndarray, pred_women: np.ndarray) -> float:
    pred_total = np.maximum(pred_men, 0.0) + np.maximum(pred_women, 0.0)
    true_total = test["total"].astype(float).to_numpy()
    return float(np.mean(np.abs(pred_total - true_total)))


def _baseline_mae(test: pd.DataFrame) -> float | None:
    if "same_dow_last_week_total" not in test.columns:
        return None
    pred = pd.to_numeric(test["same_dow_last_week_total"], errors="coerce").to_numpy()
    true = pd.to_numeric(test["total"], errors="coerce").to_numpy()
    mask = ~(np.isnan(pred) | np.isnan(true))
    if not mask.any():
        return None
    return float(np.mean(np.abs(pred[mask] - true[mask])))


def main() -> int:
    _load_env()
    ap = argparse.ArgumentParser(description="A/B: global pooled model vs per-store models")
    ap.add_argument("--days", type=int, default=int(os.getenv("ML_TRAIN_DAYS", "180")))
    ap.add_argument("--limit", type=int, default=int(os.getenv("ML_TRAIN_LIMIT", "1000000")))
    ap.add_argument("--min-rows", type=int, default=MIN_ROWS_PER_STORE)
    ap.add_argument("--objective", choices=["regression", "poisson", "tweedie"],
                    default=os.getenv("ML_OBJECTIVE", "regression"),
                    help="LightGBM objective to test (count-data A/B: regression=L2 vs poisson vs tweedie)")
    ap.add_argument("--json", help="optional path to write the full result as JSON")
    args = ap.parse_args()

    # Apply the chosen objective to the shared LightGBM params (metric stays mae for a fair A/B).
    LGB_PARAMS["objective"] = args.objective
    if args.objective == "tweedie":
        LGB_PARAMS["tweedie_variance_power"] = 1.3
    elif args.objective == "poisson":
        LGB_PARAMS["poisson_max_delta_step"] = 0.7

    rows = _fetch_rows(args.days, args.limit)
    df = prepare_dataframe(rows, os.getenv("TIMEZONE", "Asia/Tokyo"))
    if df.empty or "store_id" not in df.columns:
        raise SystemExit("no usable data (empty frame or missing store_id)")
    df["store_id"] = df["store_id"].astype("category")

    stores = [s for s in df["store_id"].cat.categories if (df["store_id"] == s).sum() >= args.min_rows]
    print(f"[global-ab] stores={len(stores)} rows={len(df):,} days={args.days} limit={args.limit:,} objective={args.objective}")

    # Per-store time splits (test = each store's most recent 20%)
    train_parts, test_parts, per_store = [], {}, {}
    for s in stores:
        sdf = df[df["store_id"] == s].sort_values("ts").reset_index(drop=True)
        tr, te = _time_split(sdf)
        train_parts.append(tr)
        test_parts[s] = te

    global_feats = FEATURE_COLUMNS + ["store_id"]
    train_all = pd.concat(train_parts, ignore_index=True)
    g_men = _fit(train_all, "men", global_feats, categorical=["store_id"])
    g_women = _fit(train_all, "women", global_feats, categorical=["store_id"])

    results: list[dict[str, Any]] = []
    for s in stores:
        tr = train_parts[stores.index(s)]
        te = test_parts[s]
        if te.empty:
            continue
        # per-store model
        ps_men = _fit(tr, "men", FEATURE_COLUMNS)
        ps_women = _fit(tr, "women", FEATURE_COLUMNS)
        ps_mae = _total_mae(te, ps_men.predict(te[FEATURE_COLUMNS]), ps_women.predict(te[FEATURE_COLUMNS]))
        # global model
        g_mae = _total_mae(te, g_men.predict(te[global_feats]), g_women.predict(te[global_feats]))
        # baseline
        b_mae = _baseline_mae(te)
        results.append({
            "store_id": str(s),
            "rows_test": int(len(te)),
            "per_store_mae": round(ps_mae, 3),
            "global_mae": round(g_mae, 3),
            "baseline_mae": round(b_mae, 3) if b_mae is not None else None,
        })
        per_store[str(s)] = results[-1]

    # ---- report ----
    print("\nstore                per_store   global   baseline   winner")
    print("-" * 64)
    g_wins = ps_wins = ties = 0
    g_beats_base = ps_beats_base = 0
    for r in sorted(results, key=lambda x: x["store_id"]):
        ps, g, b = r["per_store_mae"], r["global_mae"], r["baseline_mae"]
        if g < ps - 1e-9:
            winner = "GLOBAL"; g_wins += 1
        elif ps < g - 1e-9:
            winner = "per-store"; ps_wins += 1
        else:
            winner = "tie"; ties += 1
        if b is not None:
            g_beats_base += int(g < b)
            ps_beats_base += int(ps < b)
        bstr = f"{b:8.3f}" if b is not None else "     n/a"
        print(f"{r['store_id']:<18} {ps:9.3f} {g:8.3f} {bstr}   {winner}")

    n = len(results)
    mean_ps = float(np.mean([r["per_store_mae"] for r in results])) if n else 0.0
    mean_g = float(np.mean([r["global_mae"] for r in results])) if n else 0.0
    bvals = [r["baseline_mae"] for r in results if r["baseline_mae"] is not None]
    mean_b = float(np.mean(bvals)) if bvals else None
    print("-" * 64)
    print(f"stores compared      : {n}")
    print(f"global wins / ties / per-store wins : {g_wins} / {ties} / {ps_wins}")
    print(f"mean total MAE       : per_store={mean_ps:.3f}  global={mean_g:.3f}"
          + (f"  baseline={mean_b:.3f}" if mean_b is not None else ""))
    if bvals:
        print(f"beat baseline        : global={g_beats_base}/{len(bvals)}  per_store={ps_beats_base}/{len(bvals)}")
    verdict = ("GLOBAL looks better or equal — worth adopting (re-check on a second run)"
               if mean_g <= mean_ps + 1e-9 else
               "per-store still better on average — keep per-store, revisit as data grows")
    print(f"\nVERDICT: {verdict}")
    print("NOTE: single 80/20 split, fixed params (no Optuna). For a decision, also run "
          "rolling-origin backtests and confirm flagship stores do not regress.")

    if args.json:
        Path(args.json).write_text(json.dumps({
            "config": {"days": args.days, "limit": args.limit, "min_rows": args.min_rows, "objective": args.objective},
            "summary": {
                "stores": n, "global_wins": g_wins, "ties": ties, "per_store_wins": ps_wins,
                "mean_per_store_mae": round(mean_ps, 3), "mean_global_mae": round(mean_g, 3),
                "mean_baseline_mae": round(mean_b, 3) if mean_b is not None else None,
            },
            "per_store": per_store,
        }, ensure_ascii=True, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
