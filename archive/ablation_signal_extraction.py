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
        ]
        if cfg.store_id:
            params.append(("store_id", f"eq.{cfg.store_id}"))
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


def _gain_map(model: XGBClassifier, feature_cols: list[str]) -> dict[str, float]:
    score = model.get_booster().get_score(importance_type="gain")
    fmap = {f"f{i}": col for i, col in enumerate(feature_cols)}
    out: dict[str, float] = {}
    for k, v in score.items():
        out[fmap.get(k, k)] = float(v)
    return out


def _build_sets(feature_cols: list[str]) -> dict[str, list[str]]:
    ma_cols = [c for c in feature_cols if c.startswith("men_ma_") or c.startswith("women_ma_")]
    lag_cols = [c for c in feature_cols if c.startswith("men_lag_") or c.startswith("women_lag_")]
    ar_now = ["gender_diff"]
    full = feature_cols.copy()
    no_ma = [c for c in full if c not in set(ma_cols)]
    no_ar = [c for c in full if c not in set(ma_cols + lag_cols + ar_now)]
    return {"full": full, "no_ma": no_ma, "no_autoregressive": no_ar}


def _to_metrics(y_true: np.ndarray, proba: np.ndarray) -> dict[str, Any]:
    pred = (proba >= 0.5).astype(int)
    return {
        "rows": int(len(y_true)),
        "accuracy": float(accuracy_score(y_true, pred)),
        "auc": float(roc_auc_score(y_true, proba)) if len(np.unique(y_true)) > 1 else None,
        "positive_rate_true": float(np.mean(y_true)),
        "positive_rate_pred": float(np.mean(pred)),
    }


def _run_single(
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    *,
    feature_cols: list[str],
    max_depth: int,
    learning_rate: float,
    n_estimators: int,
) -> tuple[dict[str, Any], dict[str, float], dict[str, float] | None]:
    model = XGBClassifier(
        n_estimators=n_estimators,
        max_depth=max_depth,
        learning_rate=learning_rate,
        subsample=0.8,
        colsample_bytree=0.9,
        objective="binary:logistic",
        eval_metric="auc",
        random_state=42,
    )
    model.fit(
        train_df[feature_cols],
        train_df["y_up"].to_numpy(),
        eval_set=[(test_df[feature_cols], test_df["y_up"].to_numpy())],
        verbose=False,
    )
    proba = model.predict_proba(test_df[feature_cols])[:, 1]
    metrics = _to_metrics(test_df["y_up"].to_numpy(), proba)
    gains = _gain_map(model, feature_cols)

    shap_abs_mean: dict[str, float] | None = None
    try:
        import shap  # type: ignore

        sample_n = min(1500, len(test_df))
        if sample_n > 0:
            sample = test_df[feature_cols].iloc[-sample_n:]
            explainer = shap.TreeExplainer(model)
            shap_vals = explainer.shap_values(sample)
            arr = np.array(shap_vals)
            if arr.ndim == 2:
                shap_abs_mean = {
                    col: float(val)
                    for col, val in zip(feature_cols, np.mean(np.abs(arr), axis=0), strict=False)
                }
    except Exception:
        shap_abs_mean = None

    return metrics, gains, shap_abs_mean


def _segment_mask(df: pd.DataFrame) -> pd.Series:
    # 金・土・祝前日 かつ 20:00-00:59（20時〜25時）
    return (
        (df["hour"].isin([20, 21, 22, 23, 0]))
        & ((df["dow"].isin([4, 5])) | (df["is_pre_holiday"] == 1))
    )


def main() -> int:
    _load_env()
    parser = argparse.ArgumentParser(description="Signal extraction ablation for 60m delta direction")
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
    print(f"[split] all train={len(train_df)} test={len(test_df)}")

    feature_sets = _build_sets(FEATURE_COLUMNS)
    watch = [
        "days_from_25th",
        "minutes_to_midnight",
        "precip_mm",
        "feat_payday_night_peak",
        "feat_rain_night_exit",
        "feat_pre_holiday_surge",
    ]

    ablation: dict[str, Any] = {}
    for name, cols in feature_sets.items():
        metrics, gains, shap_abs_mean = _run_single(
            train_df,
            test_df,
            feature_cols=cols,
            max_depth=args.max_depth,
            learning_rate=args.learning_rate,
            n_estimators=args.n_estimators,
        )
        ablation[name] = {
            "feature_count": len(cols),
            "metrics": metrics,
            "watch_gain": {k: float(gains.get(k, 0.0)) for k in watch},
            "watch_shap_abs_mean": ({k: float(shap_abs_mean.get(k, 0.0)) for k in watch} if shap_abs_mean else None),
        }
        print(f"[ablation][{name}] auc={metrics['auc']} watch_gain={ablation[name]['watch_gain']}")

    seg_train = train_df[_segment_mask(train_df)].copy()
    seg_test = test_df[_segment_mask(test_df)].copy()
    print(f"[segment] train={len(seg_train)} test={len(seg_test)}")
    segment_result: dict[str, Any] | None = None
    if len(seg_train) >= 500 and len(seg_test) >= 200 and seg_train["y_up"].nunique() >= 2 and seg_test["y_up"].nunique() >= 2:
        metrics, gains, shap_abs_mean = _run_single(
            seg_train,
            seg_test,
            feature_cols=FEATURE_COLUMNS,
            max_depth=args.max_depth,
            learning_rate=args.learning_rate,
            n_estimators=args.n_estimators,
        )
        segment_result = {
            "feature_count": len(FEATURE_COLUMNS),
            "metrics": metrics,
            "watch_gain": {k: float(gains.get(k, 0.0)) for k in watch},
            "watch_shap_abs_mean": ({k: float(shap_abs_mean.get(k, 0.0)) for k in watch} if shap_abs_mean else None),
        }
        print(f"[segment][full] auc={metrics['auc']} watch_gain={segment_result['watch_gain']}")

    out = {
        "store_id": cfg.store_id if cfg.store_id else "all",
        "rows_fetched": int(len(rows)),
        "horizon_min": int(args.horizon_min),
        "feature_columns_count": len(FEATURE_COLUMNS),
        "ablation": ablation,
        "segment_peak_fri_sat_preholiday_20_25": segment_result,
    }

    out_dir = REPO_ROOT / "artifacts"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"ablation_signal_extraction_{ts}.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("[result] report", out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
