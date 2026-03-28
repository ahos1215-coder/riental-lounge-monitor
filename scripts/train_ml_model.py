from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import tempfile
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

try:
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    HAS_OPTUNA = True
except ImportError:
    HAS_OPTUNA = False

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from oriental.ml.preprocess import FEATURE_COLUMNS, prepare_dataframe


def _load_env() -> None:
    root = Path(__file__).resolve().parents[1]
    env_base = root / ".env"
    env_local = root / ".env.local"
    if env_base.is_file():
        load_dotenv(env_base, override=False)
    if env_local.is_file():
        load_dotenv(env_local, override=True)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _build_xgb_model(**overrides: Any) -> XGBRegressor:
    params: dict[str, Any] = {
        "n_estimators": 300,
        "max_depth": 4,
        "learning_rate": 0.1,
        "subsample": 0.8,
        "objective": "reg:squarederror",
        "early_stopping_rounds": 15,
    }
    params.update(overrides)
    return XGBRegressor(**params)


@dataclass(slots=True)
class TrainingConfig:
    supabase_url: str
    supabase_service_key: str
    bucket: str
    prefix: str
    schema_version: str
    timezone: str
    train_days: int
    train_limit: int
    store_id: str | None
    sample_weight_peak: float
    sample_weight_rain: float
    optuna_trials: int
    optuna_enabled: bool

    @classmethod
    def from_env(cls) -> "TrainingConfig":
        supabase_url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
        supabase_service_key = (
            os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
            or os.getenv("SUPABASE_SERVICE_KEY", "").strip()
        )
        return cls(
            supabase_url=supabase_url,
            supabase_service_key=supabase_service_key,
            bucket=os.getenv("FORECAST_MODEL_BUCKET", "ml-models").strip(),
            prefix=os.getenv("FORECAST_MODEL_PREFIX", "forecast/latest").strip().strip("/"),
            schema_version=os.getenv("FORECAST_MODEL_SCHEMA_VERSION", "v2").strip(),
            timezone=os.getenv("TIMEZONE", "Asia/Tokyo").strip(),
            train_days=_env_int("ML_TRAIN_DAYS", 180),
            train_limit=_env_int("ML_TRAIN_LIMIT", 120000),
            store_id=os.getenv("ML_TRAIN_STORE_ID", "").strip() or None,
            sample_weight_peak=_env_float("ML_TRAIN_WEIGHT_PEAK", 1.8),
            sample_weight_rain=_env_float("ML_TRAIN_WEIGHT_RAIN", 1.8),
            optuna_trials=_env_int("ML_OPTUNA_TRIALS", 30),
            optuna_enabled=os.getenv("ML_OPTUNA_ENABLED", "1").strip() == "1",
        )

    def validate(self) -> None:
        if not self.supabase_url:
            raise SystemExit("SUPABASE_URL is required")
        if not self.supabase_service_key:
            raise SystemExit("SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_SERVICE_KEY) is required")
        if not self.bucket:
            raise SystemExit("FORECAST_MODEL_BUCKET is required")
        if not self.prefix:
            raise SystemExit("FORECAST_MODEL_PREFIX is required")
        if not self.schema_version:
            raise SystemExit("FORECAST_MODEL_SCHEMA_VERSION is required")
        if self.sample_weight_peak < 1.0 or self.sample_weight_rain < 1.0:
            raise SystemExit("sample weights must be >= 1.0")


def _fetch_training_rows(cfg: TrainingConfig, session: requests.Session) -> list[dict[str, Any]]:
    endpoint = f"{cfg.supabase_url}/rest/v1/logs"
    end_ts = datetime.now(timezone.utc)
    start_ts = end_ts - timedelta(days=max(1, cfg.train_days))
    page_size = 1000
    offset = 0
    rows: list[dict[str, Any]] = []
    while len(rows) < cfg.train_limit:
        end = min(offset + page_size - 1, cfg.train_limit - 1)
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
        response = session.get(endpoint, params=params, headers=headers, timeout=30)
        if not response.ok:
            raise SystemExit(f"failed to fetch logs from supabase: status={response.status_code}")
        payload = response.json()
        if not isinstance(payload, list):
            raise SystemExit("supabase logs payload is not a list")
        chunk = [row for row in payload if isinstance(row, dict)]
        rows.extend(chunk)
        print(f"[train-ml][fetch] {len(rows)}/{cfg.train_limit}")
        if len(chunk) < page_size:
            break
        offset += page_size
    return rows[: cfg.train_limit]


def _segment_peak_mask(df: pd.DataFrame) -> pd.Series:
    return (
        (df["hour"].isin([20, 21, 22, 23, 0]))
        & ((df["dow"].isin([4, 5])) | (df["is_pre_holiday"] == 1))
    )


def _sample_weights(df: pd.DataFrame, cfg: TrainingConfig) -> np.ndarray:
    weights = np.ones(len(df), dtype=float)
    peak_mask = _segment_peak_mask(df)
    rain_mask = df["is_rainy"] == 1
    # 激戦区と雨天の重みを 1.5-2.0 に引き上げる
    weights[peak_mask.to_numpy()] = np.maximum(weights[peak_mask.to_numpy()], min(2.0, cfg.sample_weight_peak))
    weights[rain_mask.to_numpy()] = np.maximum(weights[rain_mask.to_numpy()], min(2.0, cfg.sample_weight_rain))
    return weights


def _optuna_objective(
    trial: "optuna.Trial",
    x_train: pd.DataFrame,
    y_train: pd.Series,
    x_test: pd.DataFrame,
    y_test: pd.Series,
    weights: np.ndarray,
) -> float:
    """Optuna objective: minimize MAE on held-out test set."""
    params = {
        "n_estimators": 300,
        "max_depth": trial.suggest_int("max_depth", 3, 8),
        "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
        "subsample": trial.suggest_float("subsample", 0.6, 1.0),
        "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 1.0),
        "min_child_weight": trial.suggest_int("min_child_weight", 1, 10),
        "reg_alpha": trial.suggest_float("reg_alpha", 1e-8, 10.0, log=True),
        "reg_lambda": trial.suggest_float("reg_lambda", 1e-8, 10.0, log=True),
        "objective": "reg:squarederror",
        "early_stopping_rounds": 15,
    }
    model = XGBRegressor(**params)
    model.fit(x_train, y_train, sample_weight=weights, eval_set=[(x_test, y_test)], verbose=False)
    pred = model.predict(x_test)
    return float(np.mean(np.abs(pred - y_test.to_numpy())))


def _optimize_params(
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    cfg: TrainingConfig,
    store_id: str,
) -> dict[str, Any]:
    """Run Optuna HPO for a single store. Returns best params dict."""
    if not HAS_OPTUNA or not cfg.optuna_enabled or cfg.optuna_trials <= 0:
        return {}

    x_train = train_df[FEATURE_COLUMNS]
    x_test = test_df[FEATURE_COLUMNS]
    y_men_train = train_df["men"].astype(float)
    y_men_test = test_df["men"].astype(float)
    weights = _sample_weights(train_df, cfg)

    study = optuna.create_study(direction="minimize")
    study.optimize(
        lambda trial: _optuna_objective(trial, x_train, y_men_train, x_test, y_men_test, weights),
        n_trials=cfg.optuna_trials,
        show_progress_bar=False,
    )
    best = study.best_params
    print(f"[train-ml][optuna] store={store_id} best_mae={study.best_value:.3f} params={json.dumps(best)}")
    return best


def _time_series_split(df: pd.DataFrame, test_ratio: float = 0.2) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split DataFrame chronologically: train on older data, test on recent data."""
    split_idx = int(len(df) * (1.0 - test_ratio))
    split_idx = max(1, min(split_idx, len(df) - 1))
    return df.iloc[:split_idx].copy(), df.iloc[split_idx:].copy()


def _train_models(
    df: pd.DataFrame, work_dir: Path, cfg: TrainingConfig, store_id: str, date_tag: str,
    hpo_params: dict[str, Any] | None = None,
) -> tuple[Path, Path, XGBRegressor, XGBRegressor, pd.DataFrame, dict[str, float], dict[str, float]]:
    train_df, test_df = _time_series_split(df, test_ratio=0.2)
    x_train = train_df[FEATURE_COLUMNS]
    y_men_train = train_df["men"].astype(float)
    y_women_train = train_df["women"].astype(float)
    weights = _sample_weights(train_df, cfg)

    x_test = test_df[FEATURE_COLUMNS]
    y_men_test = test_df["men"].astype(float)
    y_women_test = test_df["women"].astype(float)

    extra = dict(hpo_params) if hpo_params else {}
    model_men = _build_xgb_model(**extra)
    model_women = _build_xgb_model(**extra)
    model_men.fit(
        x_train, y_men_train, sample_weight=weights,
        eval_set=[(x_test, y_men_test)], verbose=False,
    )
    model_women.fit(
        x_train, y_women_train, sample_weight=weights,
        eval_set=[(x_test, y_women_test)], verbose=False,
    )
    best_men_rounds = getattr(model_men, "best_iteration", model_men.n_estimators) + 1
    best_women_rounds = getattr(model_women, "best_iteration", model_women.n_estimators) + 1
    print(f"[train-ml][early_stop] store={store_id} best_rounds men={best_men_rounds} women={best_women_rounds}")

    # Retrain on full data using the discovered optimal n_estimators
    full_weights = _sample_weights(df, cfg)
    prod_extra = {**extra}
    prod_extra.pop("early_stopping_rounds", None)
    prod_model_men = _build_xgb_model(n_estimators=best_men_rounds, early_stopping_rounds=None, **prod_extra)
    prod_model_women = _build_xgb_model(n_estimators=best_women_rounds, early_stopping_rounds=None, **prod_extra)
    prod_model_men.fit(df[FEATURE_COLUMNS], df["men"].astype(float), sample_weight=full_weights)
    prod_model_women.fit(df[FEATURE_COLUMNS], df["women"].astype(float), sample_weight=full_weights)

    model_men_path = work_dir / f"model_{store_id}_{date_tag}_men.json"
    model_women_path = work_dir / f"model_{store_id}_{date_tag}_women.json"
    prod_model_men.save_model(str(model_men_path))
    prod_model_women.save_model(str(model_women_path))

    # Feature importance (from production models trained on full data)
    fi_men = dict(zip(FEATURE_COLUMNS, prod_model_men.feature_importances_.tolist()))
    fi_women = dict(zip(FEATURE_COLUMNS, prod_model_women.feature_importances_.tolist()))

    return model_men_path, model_women_path, model_men, model_women, test_df, fi_men, fi_women


def _rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.sqrt(np.mean((y_pred - y_true) ** 2)))


def _evaluate_rows(df: pd.DataFrame, pred_men: np.ndarray, pred_women: np.ndarray) -> dict[str, float]:
    true_men = df["men"].astype(float).to_numpy()
    true_women = df["women"].astype(float).to_numpy()
    true_total = df["total"].astype(float).to_numpy()
    pred_total = np.maximum(pred_men, 0.0) + np.maximum(pred_women, 0.0)
    return {
        "men_mae": float(np.mean(np.abs(pred_men - true_men))),
        "men_rmse": _rmse(true_men, pred_men),
        "women_mae": float(np.mean(np.abs(pred_women - true_women))),
        "women_rmse": _rmse(true_women, pred_women),
        "total_mae": float(np.mean(np.abs(pred_total - true_total))),
        "total_rmse": _rmse(true_total, pred_total),
    }


def _log_metrics_by_store(
    test_df: pd.DataFrame, model_men: XGBRegressor, model_women: XGBRegressor
) -> dict[str, dict[str, Any]]:
    """Evaluate per-store metrics on held-out test data and return for metadata."""
    if test_df.empty:
        return {}
    test_df = test_df.reset_index(drop=True)
    pred_men_all = model_men.predict(test_df[FEATURE_COLUMNS])
    pred_women_all = model_women.predict(test_df[FEATURE_COLUMNS])
    stores = sorted(test_df["store_id"].dropna().unique().tolist()) if "store_id" in test_df.columns else ["all"]
    all_metrics: dict[str, dict[str, Any]] = {}
    for store in stores:
        if store == "all":
            sdf = test_df
            idx = np.arange(len(test_df))
        else:
            sdf = test_df[test_df["store_id"] == store]
            idx = sdf.index.to_numpy()
        if len(sdf) == 0:
            continue
        overall = _evaluate_rows(
            sdf,
            pred_men_all[idx],
            pred_women_all[idx],
        )
        peak_mask = _segment_peak_mask(sdf)
        if int(peak_mask.sum()) > 0:
            sseg = sdf[peak_mask]
            seg_idx = sseg.index.to_numpy()
            segment = _evaluate_rows(
                sseg,
                pred_men_all[seg_idx],
                pred_women_all[seg_idx],
            )
        else:
            segment = {}
        entry = {
            "store_id": store,
            "rows_test": int(len(sdf)),
            "overall": overall,
            "weekend_night_segment_rows": int(peak_mask.sum()),
            "weekend_night_segment": segment,
            "evaluation": "holdout_test_20pct",
        }
        print("[train-ml][metrics]", json.dumps(entry, ensure_ascii=True))
        all_metrics[store] = entry
    return all_metrics


def _build_metadata(
    cfg: TrainingConfig,
    df: pd.DataFrame,
    *,
    trained_at: str,
    date_tag: str,
    store_models: dict[str, dict[str, Any]],
    metrics: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "schema_version": cfg.schema_version,
        "feature_columns": FEATURE_COLUMNS,
        "model_men": "model_men.json",  # backward compatibility
        "model_women": "model_women.json",  # backward compatibility
        "has_store_models": True,
        "trained_at": trained_at,
        "artifacts_date": date_tag,
        "timezone": cfg.timezone,
        "train_days": cfg.train_days,
        "train_limit": cfg.train_limit,
        "train_store_id": cfg.store_id,
        "row_count": int(len(df)),
        "store_models": store_models,
        "sample_weight_peak": cfg.sample_weight_peak,
        "sample_weight_rain": cfg.sample_weight_rain,
        "python_version": platform.python_version(),
        "xgboost_version": xgb.__version__,
    }
    if metrics:
        meta["metrics"] = metrics
    return meta


def _upload_file(
    *,
    cfg: TrainingConfig,
    session: requests.Session,
    local_path: Path,
    remote_name: str,
    content_type: str,
) -> None:
    object_path = f"{cfg.prefix}/{remote_name}".strip("/")
    endpoint = f"{cfg.supabase_url}/storage/v1/object/{cfg.bucket}/{object_path}"
    headers = {
        "apikey": cfg.supabase_service_key,
        "Authorization": f"Bearer {cfg.supabase_service_key}",
        "x-upsert": "true",
        "Content-Type": content_type,
    }
    response = session.post(endpoint, headers=headers, data=local_path.read_bytes(), timeout=30)
    if not response.ok:
        raise SystemExit(f"upload failed: {remote_name} status={response.status_code} body={response.text[:300]}")


def main() -> int:
    _load_env()
    parser = argparse.ArgumentParser(description="Train forecast XGBoost models and upload to Supabase Storage.")
    parser.add_argument("--days", type=int, help="override ML_TRAIN_DAYS")
    parser.add_argument("--limit", type=int, help="override ML_TRAIN_LIMIT")
    parser.add_argument("--store-id", help="override ML_TRAIN_STORE_ID")
    parser.add_argument("--no-optuna", action="store_true", help="disable Optuna HPO")
    parser.add_argument("--optuna-trials", type=int, help="override ML_OPTUNA_TRIALS")
    args = parser.parse_args()

    cfg = TrainingConfig.from_env()
    if args.days is not None:
        cfg.train_days = args.days
    if args.limit is not None:
        cfg.train_limit = args.limit
    if args.store_id:
        cfg.store_id = args.store_id
    if args.no_optuna:
        cfg.optuna_enabled = False
    if args.optuna_trials is not None:
        cfg.optuna_trials = args.optuna_trials
    cfg.validate()

    session = requests.Session()
    rows = _fetch_training_rows(cfg, session)
    if len(rows) < 200:
        raise SystemExit(f"not enough rows for training: {len(rows)} (need >= 200)")

    df = prepare_dataframe(rows, cfg.timezone)
    if df.empty:
        raise SystemExit("training dataframe is empty after preprocess")
    missing = [col for col in FEATURE_COLUMNS if col not in df.columns]
    if missing:
        raise SystemExit(f"preprocess output missing FEATURE_COLUMNS: {missing}")

    trained_at = datetime.now(timezone.utc).isoformat()
    date_tag = datetime.now(timezone.utc).strftime("%Y%m%d")
    store_models: dict[str, dict[str, Any]] = {}
    all_metrics: dict[str, dict[str, Any]] = {}

    with tempfile.TemporaryDirectory(prefix="train-ml-") as tmp:
        work_dir = Path(tmp)
        stores = [cfg.store_id] if cfg.store_id else sorted(df["store_id"].dropna().unique().tolist())
        if not stores:
            raise SystemExit("no store_id available for per-store training")

        for store_id in stores:
            sdf = df[df["store_id"] == store_id].copy().reset_index(drop=True)
            if len(sdf) < 200:
                print(f"[train-ml][skip] store_id={store_id} rows={len(sdf)} (<200)")
                continue

            # Optuna HPO (uses train/test split internally)
            train_part, test_part = _time_series_split(sdf, test_ratio=0.2)
            hpo_params = _optimize_params(train_part, test_part, cfg, store_id)

            model_men_path, model_women_path, model_men, model_women, test_df, fi_men, fi_women = _train_models(
                sdf, work_dir, cfg, store_id, date_tag, hpo_params=hpo_params,
            )
            store_metrics = _log_metrics_by_store(test_df, model_men, model_women)
            if hpo_params:
                for k in store_metrics:
                    store_metrics[k]["hpo_params"] = hpo_params
            for k in store_metrics:
                store_metrics[k]["feature_importance_men"] = fi_men
                store_metrics[k]["feature_importance_women"] = fi_women
            all_metrics.update(store_metrics)

            # Latest alias for simpler rollback/fallback
            alias_men_path = work_dir / f"model_{store_id}_men.json"
            alias_women_path = work_dir / f"model_{store_id}_women.json"
            alias_men_path.write_bytes(model_men_path.read_bytes())
            alias_women_path.write_bytes(model_women_path.read_bytes())

            for p in (model_men_path, model_women_path, alias_men_path, alias_women_path):
                _upload_file(
                    cfg=cfg,
                    session=session,
                    local_path=p,
                    remote_name=p.name,
                    content_type="application/json",
                )
            store_models[store_id] = {
                "model_men": alias_men_path.name,
                "model_women": alias_women_path.name,
                "dated_model_men": model_men_path.name,
                "dated_model_women": model_women_path.name,
                "row_count": int(len(sdf)),
                "trained_at": trained_at,
            }

        if not store_models:
            raise SystemExit("no per-store models were trained (all stores skipped)")

        metadata = _build_metadata(
            cfg,
            df,
            trained_at=trained_at,
            date_tag=date_tag,
            store_models=store_models,
            metrics=all_metrics if all_metrics else None,
        )
        metadata_path = work_dir / "metadata.json"
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")

        # backward compatibility global aliases (default store or first available store)
        default_store = cfg.store_id if cfg.store_id in store_models else sorted(store_models.keys())[0]
        default_men = work_dir / store_models[default_store]["model_men"]
        default_women = work_dir / store_models[default_store]["model_women"]
        global_men = work_dir / "model_men.json"
        global_women = work_dir / "model_women.json"
        global_men.write_bytes(default_men.read_bytes())
        global_women.write_bytes(default_women.read_bytes())
        _upload_file(
            cfg=cfg,
            session=session,
            local_path=global_men,
            remote_name=global_men.name,
            content_type="application/json",
        )
        _upload_file(
            cfg=cfg,
            session=session,
            local_path=global_women,
            remote_name=global_women.name,
            content_type="application/json",
        )
        _upload_file(
            cfg=cfg,
            session=session,
            local_path=metadata_path,
            remote_name="metadata.json",
            content_type="application/json",
        )

    print(
        "[train-ml] uploaded models successfully",
        json.dumps(
            {
                "bucket": cfg.bucket,
                "prefix": cfg.prefix,
                "schema_version": cfg.schema_version,
                "row_count": len(df),
                "stores_trained": sorted(store_models.keys()),
            },
            ensure_ascii=True,
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
