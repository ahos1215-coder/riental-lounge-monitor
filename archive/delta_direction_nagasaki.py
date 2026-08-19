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
from dotenv import load_dotenv
from sklearn.metrics import accuracy_score, roc_auc_score
from xgboost import XGBClassifier

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
    offset = 0
    while len(rows) < cfg.limit:
        end = min(offset + page_size - 1, cfg.limit - 1)
        params: list[tuple[str, str]] = [
            ("select", "store_id,ts,men,women,total,weather_code,temp_c,precip_mm"),
            ("order", "ts.asc"),
            ("limit", str(page_size)),
            ("offset", str(offset)),
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
            "Range": f"{offset}-{end}",
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
        offset += page_size
    return rows[: cfg.limit]


def _gain_watch(model: XGBClassifier, feature_cols: list[str], watch: list[str]) -> dict[str, float]:
    score = model.get_booster().get_score(importance_type="gain")
    fmap = {f"f{i}": col for i, col in enumerate(feature_cols)}
    rev = {v: k for k, v in fmap.items()}
    return {w: float(score.get(rev.get(w, ""), 0.0)) for w in watch}


def main() -> int:
    _load_env()
    parser = argparse.ArgumentParser(description="Delta direction classification (Nagasaki)")
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--limit", type=int, default=200000)
    parser.add_argument("--store-id", default="ol_nagasaki")
    parser.add_argument("--horizon-min", type=int, default=60)
    parser.add_argument("--max-depth", type=int, default=7)
    parser.add_argument("--learning-rate", type=float, default=0.05)
    parser.add_argument("--n-estimators", type=int, default=1000)
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
    if args.horizon_min <= 0 or args.horizon_min % 5 != 0:
        raise SystemExit("horizon-min must be positive multiple of 5")

    rows = _fetch_rows(cfg, requests.Session())
    df = prepare_dataframe(rows, cfg.timezone).sort_values("ts").reset_index(drop=True)
    step = args.horizon_min // 5
    df["y_total_t"] = df["total"].shift(-step)
    df["y_delta"] = df["y_total_t"] - df["total"]
    df = df.dropna(subset=["y_delta"]).reset_index(drop=True)
    df["y_up"] = (df["y_delta"] > 0).astype(int)

    split_idx = int(len(df) * 0.8)
    train_df = df.iloc[:split_idx].copy()
    test_df = df.iloc[split_idx:].copy()
    print(f"[split] train={len(train_df)} test={len(test_df)} horizon={args.horizon_min}m")

    model = XGBClassifier(
        n_estimators=args.n_estimators,
        max_depth=args.max_depth,
        learning_rate=args.learning_rate,
        subsample=0.8,
        colsample_bytree=0.9,
        objective="binary:logistic",
        eval_metric="auc",
        random_state=42,
    )
    model.fit(
        train_df[FEATURE_COLUMNS],
        train_df["y_up"].to_numpy(),
        eval_set=[(test_df[FEATURE_COLUMNS], test_df["y_up"].to_numpy())],
        verbose=False,
    )

    proba = model.predict_proba(test_df[FEATURE_COLUMNS])[:, 1]
    pred = (proba >= 0.5).astype(int)
    y_true = test_df["y_up"].to_numpy()
    out_metrics: dict[str, Any] = {
        "rows": int(len(test_df)),
        "accuracy": float(accuracy_score(y_true, pred)),
        "auc": float(roc_auc_score(y_true, proba)) if len(np.unique(y_true)) > 1 else None,
        "positive_rate_true": float(np.mean(y_true)),
        "positive_rate_pred": float(np.mean(pred)),
    }

    watch = [
        "days_from_25th",
        "minutes_to_midnight",
        "precip_mm",
        "feat_payday_night_peak",
        "feat_rain_night_exit",
        "feat_pre_holiday_surge",
    ]
    gain = _gain_watch(model, FEATURE_COLUMNS, watch)

    report = {
        "store_id": cfg.store_id,
        "rows_fetched": int(len(rows)),
        "horizon_min": int(args.horizon_min),
        "metrics": out_metrics,
        "gain_watch_features": gain,
    }

    out_dir = REPO_ROOT / "artifacts"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"delta_direction_nagasaki_{args.horizon_min}m_{ts}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("[direction] report", out_path)
    print("[direction] metrics", json.dumps(out_metrics, ensure_ascii=False))
    print("[direction] gain_watch_features", json.dumps(gain, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
