from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests
import xgboost as xgb
from dotenv import load_dotenv
from xgboost import XGBRegressor

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from oriental.ml.preprocess import FEATURE_COLUMNS, prepare_dataframe


def _load_env() -> None:
    env_base = REPO_ROOT / ".env"
    env_local = REPO_ROOT / ".env.local"
    if env_base.is_file():
        load_dotenv(env_base, override=False)
    if env_local.is_file():
        load_dotenv(env_local, override=True)


@dataclass(slots=True)
class Cfg:
    supabase_url: str
    supabase_service_key: str
    timezone: str
    days: int
    limit: int
    store_id: str


def _fetch_rows(cfg: Cfg, session: requests.Session) -> list[dict[str, Any]]:
    endpoint = f"{cfg.supabase_url}/rest/v1/logs"
    end_ts = datetime.now(timezone.utc)
    start_ts = end_ts - timedelta(days=max(1, cfg.days))
    page_size = 1000
    rows: list[dict[str, Any]] = []
    start = 0
    while len(rows) < cfg.limit:
        end = min(start + page_size - 1, cfg.limit - 1)
        params: list[tuple[str, str]] = [
            ("select", "store_id,ts,men,women,total,weather_code,temp_c,precip_mm"),
            ("order", "ts.asc"),
            ("limit", str(page_size)),
            ("offset", str(start)),
            ("ts", f"gte.{start_ts.isoformat()}"),
            ("ts", f"lte.{end_ts.isoformat()}"),
            ("men", "not.is.null"),
            ("women", "not.is.null"),
            ("store_id", f"eq.{cfg.store_id}"),
        ]
        headers = {
            "apikey": cfg.supabase_service_key,
            "Authorization": f"Bearer {cfg.supabase_service_key}",
            "Accept": "application/json",
            "Range-Unit": "items",
            "Range": f"{start}-{end}",
        }
        resp = session.get(endpoint, params=params, headers=headers, timeout=30)
        if not resp.ok:
            raise SystemExit(f"fetch failed status={resp.status_code} body={resp.text[:200]}")
        payload = resp.json()
        if not isinstance(payload, list):
            raise SystemExit("invalid payload")
        chunk = [r for r in payload if isinstance(r, dict)]
        rows.extend(chunk)
        print(f"[fetch] {len(rows)}/{cfg.limit} rows fetched...")
        if len(chunk) < page_size:
            break
        start += page_size
    return rows[: cfg.limit]


def _build_model(max_depth: int, learning_rate: float, n_estimators: int, early_stopping_rounds: int) -> XGBRegressor:
    callbacks = []
    if early_stopping_rounds > 0:
        callbacks.append(xgb.callback.EarlyStopping(rounds=early_stopping_rounds, save_best=True))
    return XGBRegressor(
        n_estimators=n_estimators,
        max_depth=max_depth,
        learning_rate=learning_rate,
        subsample=0.8,
        colsample_bytree=0.9,
        objective="reg:squarederror",
        eval_metric="rmse",
        random_state=42,
        callbacks=callbacks,
    )


def _rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.sqrt(np.mean((y_pred - y_true) ** 2)))


def _evaluate(df_test: pd.DataFrame, pred_delta: np.ndarray, y_total_col: str) -> dict[str, Any]:
    pred_total = np.maximum(df_test["total"].astype(float).to_numpy() + pred_delta, 0.0)
    y_true_total = df_test[y_total_col].astype(float).to_numpy()
    err = pred_total - y_true_total
    out: dict[str, Any] = {
        "rows": int(len(df_test)),
        "mae": float(np.abs(err).mean()),
        "rmse": _rmse(y_true_total, pred_total),
    }
    rainy = df_test["is_rainy"] == 1
    if int(rainy.sum()) > 0:
        p = pred_total[rainy.to_numpy()]
        y = y_true_total[rainy.to_numpy()]
        out["rainy_rows"] = int(rainy.sum())
        out["rainy_mae"] = float(np.abs(p - y).mean())
        out["rainy_rmse"] = _rmse(y, p)
    h = df_test["ts"].dt.hour
    night = h.isin([21, 22, 23, 0])
    if int(night.sum()) > 0:
        p = pred_total[night.to_numpy()]
        y = y_true_total[night.to_numpy()]
        out["h21_25_rows"] = int(night.sum())
        out["h21_25_mae"] = float(np.abs(p - y).mean())
        out["h21_25_rmse"] = _rmse(y, p)
    return out


def _gain_watch(model: XGBRegressor, feature_cols: list[str], watch: list[str]) -> dict[str, float]:
    score = model.get_booster().get_score(importance_type="gain")
    fmap = {f"f{i}": col for i, col in enumerate(feature_cols)}
    rev = {v: k for k, v in fmap.items()}
    return {w: float(score.get(rev.get(w, ""), 0.0)) for w in watch}


def main() -> int:
    _load_env()
    parser = argparse.ArgumentParser(description="Delta target experiment for one store")
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--limit", type=int, default=200000)
    parser.add_argument("--store-id", default="ol_nagasaki")
    parser.add_argument("--max-depth", type=int, default=7)
    parser.add_argument("--learning-rate", type=float, default=0.05)
    parser.add_argument("--n-estimators", type=int, default=1000)
    parser.add_argument("--early-stopping-rounds", type=int, default=50)
    parser.add_argument("--horizons-min", default="30,60", help="Comma separated forecast horizons in minutes")
    args = parser.parse_args()

    cfg = Cfg(
        supabase_url=os.getenv("SUPABASE_URL", "").strip().rstrip("/"),
        supabase_service_key=(
            os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
            or os.getenv("SUPABASE_SERVICE_KEY", "").strip()
        ),
        timezone=os.getenv("TIMEZONE", "Asia/Tokyo").strip(),
        days=args.days,
        limit=args.limit,
        store_id=args.store_id.strip(),
    )
    if not cfg.supabase_url or not cfg.supabase_service_key:
        raise SystemExit("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY/SUPABASE_SERVICE_KEY are required")

    rows = _fetch_rows(cfg, requests.Session())
    if len(rows) < 2000:
        raise SystemExit(f"not enough rows: {len(rows)}")

    df_base = prepare_dataframe(rows, cfg.timezone).sort_values("ts").reset_index(drop=True)
    horizons = [int(h.strip()) for h in str(args.horizons_min).split(",") if str(h).strip()]
    if not horizons:
        raise SystemExit("horizons-min is empty")

    experiments: dict[str, Any] = {}
    watch = [
        "days_from_25th",
        "next_morning_rain",
        "minutes_to_midnight",
        "is_holiday",
        "precip_mm",
        "feat_payday_night_peak",
        "feat_rain_night_exit",
        "feat_pre_holiday_surge",
    ]

    for horizon_min in horizons:
        if horizon_min <= 0 or horizon_min % 5 != 0:
            raise SystemExit(f"invalid horizon: {horizon_min} (must be positive and multiple of 5)")
        step = horizon_min // 5
        y_total_col = f"y_total_t{horizon_min}"
        y_delta_col = f"y_delta_total_t{horizon_min}"

        df = df_base.copy()
        df[y_total_col] = df["total"].shift(-step)
        df[y_delta_col] = df[y_total_col] - df["total"]
        df = df.dropna(subset=[y_total_col, y_delta_col]).reset_index(drop=True)
        split_idx = int(len(df) * 0.8)
        train_df = df.iloc[:split_idx].copy()
        test_df = df.iloc[split_idx:].copy()
        print(f"[split][{horizon_min}m] train={len(train_df)} test={len(test_df)}")

        model = _build_model(
            max_depth=args.max_depth,
            learning_rate=args.learning_rate,
            n_estimators=args.n_estimators,
            early_stopping_rounds=args.early_stopping_rounds,
        )
        model.fit(
            train_df[FEATURE_COLUMNS],
            train_df[y_delta_col].astype(float).to_numpy(),
            eval_set=[(test_df[FEATURE_COLUMNS], test_df[y_delta_col].astype(float).to_numpy())],
            verbose=False,
        )
        pred_delta = model.predict(test_df[FEATURE_COLUMNS]).astype(float)
        metrics = _evaluate(test_df, pred_delta, y_total_col=y_total_col)
        gain = _gain_watch(model, FEATURE_COLUMNS, watch)
        experiments[str(horizon_min)] = {
            "target": f"delta_total_{horizon_min}min",
            "rows_after_labeling": int(len(df)),
            "train_rows": int(len(train_df)),
            "test_rows": int(len(test_df)),
            "metrics": metrics,
            "gain_watch_features": gain,
        }
        print(f"[delta][{horizon_min}m] metrics", json.dumps(metrics, ensure_ascii=False))
        print(f"[delta][{horizon_min}m] gain_watch_features", json.dumps(gain, ensure_ascii=False))

    out = {
        "store_id": cfg.store_id,
        "rows_fetched": int(len(rows)),
        "hyperparams": {
            "max_depth": args.max_depth,
            "learning_rate": args.learning_rate,
            "n_estimators": args.n_estimators,
            "early_stopping_rounds": args.early_stopping_rounds,
        },
        "experiments": experiments,
    }

    out_dir = REPO_ROOT / "artifacts"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"delta_nagasaki_report_{ts}.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("[delta] report", out_path)
    print("[delta] rows_fetched", out["rows_fetched"])
    print("[delta] experiments", ",".join(sorted(experiments.keys())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
