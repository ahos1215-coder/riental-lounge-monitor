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
    out_dir: Path

    @classmethod
    def from_env(cls, days: int, limit: int, store_id: str) -> "Cfg":
        return cls(
            supabase_url=os.getenv("SUPABASE_URL", "").strip().rstrip("/"),
            supabase_service_key=(
                os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
                or os.getenv("SUPABASE_SERVICE_KEY", "").strip()
            ),
            timezone=os.getenv("TIMEZONE", "Asia/Tokyo").strip(),
            days=days,
            limit=limit,
            store_id=store_id.strip(),
            out_dir=REPO_ROOT / "artifacts",
        )

    def validate(self) -> None:
        if not self.supabase_url or not self.supabase_service_key:
            raise SystemExit("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY/SUPABASE_SERVICE_KEY are required")


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


def _build_model(
    *,
    max_depth: int,
    learning_rate: float,
    n_estimators: int,
    early_stopping_rounds: int,
) -> XGBRegressor:
    callbacks = []
    if early_stopping_rounds > 0:
        callbacks.append(xgb.callback.EarlyStopping(rounds=early_stopping_rounds, save_best=True))
    return XGBRegressor(
        n_estimators=n_estimators,
        max_depth=max_depth,
        learning_rate=learning_rate,
        subsample=0.8,
        colsample_bytree=0.9,
        min_child_weight=1,
        objective="reg:squarederror",
        eval_metric="rmse",
        random_state=42,
        callbacks=callbacks,
    )


def _rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(y_pred - y_true))))


def _evaluate(
    df_test: pd.DataFrame,
    men_pred: np.ndarray,
    women_pred: np.ndarray,
    *,
    label: str,
) -> dict[str, Any]:
    pred_total = np.maximum(men_pred, 0) + np.maximum(women_pred, 0)
    true_total = df_test["total"].astype(float).to_numpy()
    abs_err = np.abs(pred_total - true_total)
    out: dict[str, Any] = {
        "label": label,
        "rows": int(len(df_test)),
        "mae": float(abs_err.mean()),
        "rmse": _rmse(true_total, pred_total),
    }
    rainy = df_test["is_rainy"] == 1
    if int(rainy.sum()) > 0:
        y = true_total[rainy.to_numpy()]
        p = pred_total[rainy.to_numpy()]
        out["rainy_rows"] = int(rainy.sum())
        out["rainy_mae"] = float(np.abs(p - y).mean())
        out["rainy_rmse"] = _rmse(y, p)
    payday = df_test["is_payday_week"] == 1
    if int(payday.sum()) > 0:
        y = true_total[payday.to_numpy()]
        p = pred_total[payday.to_numpy()]
        out["payday_rows"] = int(payday.sum())
        out["payday_mae"] = float(np.abs(p - y).mean())
        out["payday_rmse"] = _rmse(y, p)
    return out


def _gain_for_features(model_men: XGBRegressor, model_women: XGBRegressor, feature_cols: list[str], targets: list[str]) -> dict[str, Any]:
    men_score = model_men.get_booster().get_score(importance_type="gain")
    women_score = model_women.get_booster().get_score(importance_type="gain")
    fmap = {f"f{i}": c for i, c in enumerate(feature_cols)}
    out: dict[str, Any] = {}
    for f in targets:
        men_gain = float(men_score.get(next((k for k, v in fmap.items() if v == f), ""), 0.0))
        women_gain = float(women_score.get(next((k for k, v in fmap.items() if v == f), ""), 0.0))
        out[f] = {"men_gain": men_gain, "women_gain": women_gain, "avg_gain": (men_gain + women_gain) / 2.0}
    return out


def main() -> int:
    _load_env()
    parser = argparse.ArgumentParser(description="Ablation study: remove MA features and compare")
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--limit", type=int, default=200000)
    parser.add_argument("--store-id", default="ol_nagasaki")
    parser.add_argument("--max-depth", type=int, default=7)
    parser.add_argument("--learning-rate", type=float, default=0.05)
    parser.add_argument("--n-estimators", type=int, default=1000)
    parser.add_argument("--early-stopping-rounds", type=int, default=50)
    args = parser.parse_args()

    cfg = Cfg.from_env(days=args.days, limit=args.limit, store_id=args.store_id)
    cfg.validate()
    cfg.out_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    rows = _fetch_rows(cfg, session)
    if len(rows) < 2000:
        raise SystemExit(f"not enough rows: {len(rows)}")
    df = prepare_dataframe(rows, cfg.timezone)
    df = df.sort_values("ts").reset_index(drop=True)

    split_idx = int(len(df) * 0.8)
    train_df = df.iloc[:split_idx].copy()
    test_df = df.iloc[split_idx:].copy()
    print(f"[split] train={len(train_df)} test={len(test_df)}")

    no_ma_cols = [c for c in FEATURE_COLUMNS if not c.startswith("men_ma_") and not c.startswith("women_ma_")]

    y_train_men = train_df["men"].astype(float).to_numpy()
    y_train_women = train_df["women"].astype(float).to_numpy()

    no_ma_men = _build_model(
        max_depth=args.max_depth,
        learning_rate=args.learning_rate,
        n_estimators=args.n_estimators,
        early_stopping_rounds=args.early_stopping_rounds,
    )
    no_ma_women = _build_model(
        max_depth=args.max_depth,
        learning_rate=args.learning_rate,
        n_estimators=args.n_estimators,
        early_stopping_rounds=args.early_stopping_rounds,
    )
    no_ma_men.fit(
        train_df[no_ma_cols],
        y_train_men,
        eval_set=[(test_df[no_ma_cols], test_df["men"].astype(float).to_numpy())],
        verbose=False,
    )
    no_ma_women.fit(
        train_df[no_ma_cols],
        y_train_women,
        eval_set=[(test_df[no_ma_cols], test_df["women"].astype(float).to_numpy())],
        verbose=False,
    )
    no_ma_eval = _evaluate(
        test_df,
        no_ma_men.predict(test_df[no_ma_cols]),
        no_ma_women.predict(test_df[no_ma_cols]),
        label="without_ma",
    )

    watch_features = ["is_payday_week", "next_morning_rain", "is_last_train_window", "is_holiday"]
    no_ma_gain = _gain_for_features(no_ma_men, no_ma_women, no_ma_cols, watch_features)

    result = {
        "rows_fetched": len(df),
        "store_id": cfg.store_id,
        "train_rows": len(train_df),
        "test_rows": len(test_df),
        "hyperparams": {
            "max_depth": args.max_depth,
            "learning_rate": args.learning_rate,
            "n_estimators": args.n_estimators,
            "early_stopping_rounds": args.early_stopping_rounds,
        },
        "metrics": {"without_ma": no_ma_eval},
        "gain_watch_features": {"without_ma": no_ma_gain},
        "removed_features": [c for c in FEATURE_COLUMNS if c not in no_ma_cols],
    }

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = cfg.out_dir / f"ablation_ma_report_{ts}.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("[ablation] report", out_path)
    print("[ablation] rows_fetched", result["rows_fetched"])
    print("[ablation] without_ma", json.dumps(no_ma_eval, ensure_ascii=False))
    print("[ablation] gain_watch_features.without_ma", json.dumps(no_ma_gain, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
