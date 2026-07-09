from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests
import xgboost as xgb
from dotenv import load_dotenv
import lightgbm as lgb

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
from oriental.utils.stores import ALL_STORE_IDS


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


def _objective_params(objective: str) -> dict[str, Any]:
    """LightGBM objective + objective-specific params.

    Counts are non-negative and intermittent (zero-heavy off-peak), so Poisson/
    Tweedie (log-link) often beat the default L2 — but this must be MEASURED, so the
    objective is env-configurable (ML_OBJECTIVE) and defaults to the current
    'regression'. metric stays 'mae' across all objectives so early-stopping, Optuna
    and the holdout report all judge by the SAME number — a fair A/B between
    objectives. Poisson/Tweedie predict >= 0 via the log-link, making the
    np.maximum(.,0) clamp in forecast_service redundant.
    """
    obj = (objective or "regression").lower()
    if obj == "poisson":
        return {"objective": "poisson", "metric": "mae", "poisson_max_delta_step": 0.7}
    if obj == "tweedie":
        return {
            "objective": "tweedie",
            "metric": "mae",
            "tweedie_variance_power": _env_float("ML_TWEEDIE_VARIANCE_POWER", 1.3),
        }
    return {"objective": "regression", "metric": "mae"}


def _build_lgb_model(objective: str = "regression", **overrides: Any) -> lgb.LGBMRegressor:
    params: dict[str, Any] = {
        "n_estimators": 300,
        "max_depth": 4,
        "learning_rate": 0.1,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "verbosity": -1,
    }
    params.update(_objective_params(objective))
    params.update(overrides)
    return lgb.LGBMRegressor(**params)


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
    objective: str
    optuna_max_rows: int
    gate_max_regression_pct: float
    stale_store_days: float
    recency_halflife_days: float
    recency_floor: float

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
            # 意図的にデフォルト値を持たせない: serving 側 (oriental/config.py) は v7 を
            # デフォルトにしているが、学習側でここが古いデフォルト(旧 v6)にずれると
            # 「ローカルで直接実行 → 気づかず古いスキーマのモデルを upload」という事故になる
            # (2026-07-06 発覚: ここが v6, config.py が v7 のまま長期間ずれていた)。
            # 未設定なら空文字のままにし、validate() で明示的に SystemExit させる。
            schema_version=os.getenv("FORECAST_MODEL_SCHEMA_VERSION", "").strip(),
            timezone=os.getenv("TIMEZONE", "Asia/Tokyo").strip(),
            train_days=_env_int("ML_TRAIN_DAYS", 180),
            # 120000 was ~180 days back when the table was small; the table has since
            # grown ~8x (≈960k rows), so a 120k cap silently shrank the effective window
            # to ~26 days. Raise the default so the ML_TRAIN_DAYS window (180d) is the
            # real bound, not the row cap. Override via ML_TRAIN_LIMIT if memory/time-bound.
            train_limit=_env_int("ML_TRAIN_LIMIT", 1_000_000),
            store_id=os.getenv("ML_TRAIN_STORE_ID", "").strip() or None,
            sample_weight_peak=_env_float("ML_TRAIN_WEIGHT_PEAK", 1.8),
            sample_weight_rain=_env_float("ML_TRAIN_WEIGHT_RAIN", 1.8),
            optuna_trials=_env_int("ML_OPTUNA_TRIALS", 30),
            optuna_enabled=os.getenv("ML_OPTUNA_ENABLED", "1").strip() == "1",
            # 'regression' (L2) keeps current behavior; 'poisson'/'tweedie' are the
            # count-data objectives to A/B (see _objective_params).
            objective=(os.getenv("ML_OBJECTIVE", "regression").strip().lower() or "regression"),
            # 0 = no cap (current behavior). If the weekly Optuna run gets too slow on the
            # ~1M-row table, set ML_OPTUNA_MAX_ROWS (e.g. 8000) to run HPO on each store's
            # most-recent N rows; the FINAL model still trains on the full data.
            optuna_max_rows=_env_int("ML_OPTUNA_MAX_ROWS", 0),
            # Champion/challenger gate (a): if a freshly-trained store's held-out test
            # total_mae is worse than the currently-deployed model's by more than this
            # percentage, the new model is NOT uploaded — the existing (champion) model
            # keeps serving and its old metadata entry is carried forward unchanged.
            gate_max_regression_pct=_env_float("ML_GATE_MAX_REGRESSION_PCT", 20.0),
            # Stale-store guard (b): stores whose newest fetched row is older than this
            # many days are skipped entirely (closed/dead stores keep their last-known
            # good model instead of being retrained on stale data forever).
            stale_store_days=_env_float("ML_STALE_STORE_DAYS", 7.0),
            # Recency weighting knobs (e): half-life (days) and floor for the exponential
            # decay in _sample_weights. Defaults (90 / 0.5) reproduce the prior hardcoded
            # behavior exactly; the daily workflow tightens these (see train-ml-model.yml)
            # to track regime shifts faster, protected by the gate above.
            recency_halflife_days=_env_float("ML_RECENCY_HALFLIFE_DAYS", 90.0),
            recency_floor=_env_float("ML_RECENCY_FLOOR", 0.5),
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
        if self.objective not in {"regression", "poisson", "tweedie"}:
            raise SystemExit("ML_OBJECTIVE must be one of: regression, poisson, tweedie")
        if self.gate_max_regression_pct < 0:
            raise SystemExit("ML_GATE_MAX_REGRESSION_PCT must be >= 0")
        if self.stale_store_days <= 0:
            raise SystemExit("ML_STALE_STORE_DAYS must be > 0")
        if self.recency_halflife_days <= 0:
            raise SystemExit("ML_RECENCY_HALFLIFE_DAYS must be > 0")
        if not (0.0 <= self.recency_floor <= 1.0):
            raise SystemExit("ML_RECENCY_FLOOR must be within [0, 1]")


def _fetch_training_rows(cfg: TrainingConfig, session: requests.Session) -> list[dict[str, Any]]:
    """Fetch recent training rows via KEYSET pagination on the unique ``id``
    (descending = newest-first).

    Why keyset, not OFFSET: once the table grew to ~1M rows, deep OFFSET pages made
    Supabase/Postgres hit a statement timeout and return HTTP 500 (observed dying at
    offset ~42k), which — with no retry — aborted the whole daily/weekly training and
    silently left the models stale. Keyset (``id=lt.<cursor>``) is O(1) per page at
    any table size, and id.desc keeps the most RECENT rows (matching the recency
    weighting). Transient 5xx/429/network errors are retried so a single blip no
    longer kills the run.
    """
    endpoint = f"{cfg.supabase_url}/rest/v1/logs"
    end_ts = datetime.now(timezone.utc)
    start_ts = end_ts - timedelta(days=max(1, cfg.train_days))
    page_size = 1000
    rows: list[dict[str, Any]] = []
    cursor: Any = None  # keyset cursor: next page fetches rows with id < cursor
    headers = {
        "apikey": cfg.supabase_service_key,
        "Authorization": f"Bearer {cfg.supabase_service_key}",
        "Accept": "application/json",
    }
    while len(rows) < cfg.train_limit:
        want = min(page_size, cfg.train_limit - len(rows))
        params: list[tuple[str, str]] = [
            ("select", "id,store_id,ts,men,women,total,weather_code,temp_c,precip_mm"),
            ("order", "id.desc"),
            ("limit", str(want)),
            ("ts", f"gte.{start_ts.isoformat()}"),
            ("ts", f"lte.{end_ts.isoformat()}"),
            ("men", "not.is.null"),
            ("women", "not.is.null"),
        ]
        if cfg.store_id:
            params.append(("store_id", f"eq.{cfg.store_id}"))
        if cursor is not None:
            params.append(("id", f"lt.{cursor}"))

        payload = None
        last_err = ""
        for attempt in range(1, 6):
            try:
                response = session.get(endpoint, params=params, headers=headers, timeout=60)
            except Exception as exc:  # noqa: BLE001 - transient network error
                last_err = str(exc)[:160]
            else:
                if response.ok:
                    payload = response.json()
                    break
                last_err = f"status={response.status_code}"
                # 4xx (except 429 rate-limit) is a real error — do not retry.
                if response.status_code < 500 and response.status_code != 429:
                    raise SystemExit(f"failed to fetch logs from supabase: {last_err}")
            if attempt < 5:
                wait = min(2 ** attempt, 20)
                print(f"[train-ml][fetch] transient error ({last_err}); retry {attempt}/5 in {wait}s")
                time.sleep(wait)
        if payload is None:
            raise SystemExit(f"failed to fetch logs from supabase after retries: {last_err}")
        if not isinstance(payload, list):
            raise SystemExit("supabase logs payload is not a list")

        chunk = [row for row in payload if isinstance(row, dict)]
        if not chunk:
            break
        rows.extend(chunk)
        cursor = chunk[-1].get("id")
        print(f"[train-ml][fetch] {len(rows)}/{cfg.train_limit}")
        if len(chunk) < want or cursor is None:
            break
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
    # 時間減衰: 直近データを重視（ML_RECENCY_HALFLIFE_DAYS 日で floor まで減衰する指数減衰）
    # floor=0.5, halflife=90 のとき、以前のハードコード式 0.5 + 0.5*exp(-days_ago/90) と
    # 完全に一致する（デフォルト挙動は不変）。
    if "ts" in df.columns:
        max_ts = df["ts"].max()
        days_ago = (max_ts - df["ts"]).dt.total_seconds() / 86400.0
        floor = cfg.recency_floor
        halflife = max(cfg.recency_halflife_days, 1e-6)
        recency = floor + (1.0 - floor) * np.exp(-days_ago.to_numpy() / halflife)
        weights *= recency
    return weights


def _optuna_objective(
    trial: "optuna.Trial",
    x_train: pd.DataFrame,
    y_train: pd.Series,
    x_test: pd.DataFrame,
    y_test: pd.Series,
    weights: np.ndarray,
    objective: str = "regression",
) -> float:
    """Optuna objective: minimize MAE on the VALIDATION set (x_test/y_test here is
    the val split passed in by the caller — the true test set is never touched
    during HPO, see _time_series_split_3)."""
    params = {
        "n_estimators": 300,
        "max_depth": trial.suggest_int("max_depth", 3, 8),
        "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
        "subsample": trial.suggest_float("subsample", 0.6, 1.0),
        "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 1.0),
        "min_child_weight": trial.suggest_int("min_child_weight", 1, 10),
        "reg_alpha": trial.suggest_float("reg_alpha", 1e-8, 10.0, log=True),
        "reg_lambda": trial.suggest_float("reg_lambda", 1e-8, 10.0, log=True),
        "verbosity": -1,
    }
    params.update(_objective_params(objective))
    model = lgb.LGBMRegressor(**params)
    model.fit(
        x_train, y_train, sample_weight=weights,
        eval_set=[(x_test, y_test)],
        callbacks=[lgb.early_stopping(15, verbose=False), lgb.log_evaluation(0)],
    )
    pred = model.predict(x_test)
    return float(np.mean(np.abs(pred - y_test.to_numpy())))


def _optimize_params(
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
    cfg: TrainingConfig,
    store_id: str,
) -> dict[str, Any]:
    """Run Optuna HPO for a single store. Fits on train_df, scores on val_df —
    the held-out test set is never passed in here, so HPO cannot leak into the
    reported metric (see _time_series_split_3). Returns best params dict."""
    if not HAS_OPTUNA or not cfg.optuna_enabled or cfg.optuna_trials <= 0:
        return {}

    # Optional: run HPO on only the most-recent rows to keep the weekly run fast
    # (default 0 = use everything). The final model is still trained on full data.
    if cfg.optuna_max_rows and cfg.optuna_max_rows > 0:
        train_df = train_df.tail(cfg.optuna_max_rows)
        val_df = val_df.tail(max(200, cfg.optuna_max_rows // 4))

    x_train = train_df[FEATURE_COLUMNS]
    x_val = val_df[FEATURE_COLUMNS]
    y_men_train = train_df["men"].astype(float)
    y_men_val = val_df["men"].astype(float)
    weights = _sample_weights(train_df, cfg)

    study = optuna.create_study(direction="minimize")
    study.optimize(
        lambda trial: _optuna_objective(trial, x_train, y_men_train, x_val, y_men_val, weights, cfg.objective),
        n_trials=cfg.optuna_trials,
        show_progress_bar=False,
    )
    best = study.best_params
    print(f"[train-ml][optuna] store={store_id} best_mae={study.best_value:.3f} params={json.dumps(best)}")
    return best


def _time_series_split_3(
    df: pd.DataFrame, val_ratio: float = 0.15, test_ratio: float = 0.15,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Split DataFrame chronologically into train / val / test (oldest -> newest).

    リーク防止のための3分割:
      - train: HPO・early-stopping のフィッティングに使う
      - val:   HPO（Optuna）と early-stopping の評価専用。ここで選んだハイパラ/
               ラウンド数は val にオーバーフィットし得るが、test には触れていない
      - test:  最終的な報告用メトリクスにのみ使う「未見データ」

    以前は train/test の2分割で、同じ test 区間を Optuna・early-stopping・報告用
    メトリクスの3箇所で使い回していたため、報告 MAE が楽観的（過小評価）になって
    いた（#4）。val を挟むことで test は本当の未見データのまま保たれる。
    """
    n = max(1, len(df))
    # 各パートが最低1行になるようにガードしつつ、val/test の希望サイズを計算する。
    # train が痩せすぎないよう、val+test で最大 n-1 行までに制限する。
    val_n = max(1, int(round(n * val_ratio)))
    test_n = max(1, int(round(n * test_ratio)))
    if val_n + test_n > n - 1:
        # 極端に小さい df の場合は val/test を1行ずつまで縮めて train を確保する
        val_n = 1
        test_n = 1
    train_n = max(1, n - val_n - test_n)
    train_end = train_n
    val_end = train_n + val_n
    return (
        df.iloc[:train_end].copy(),
        df.iloc[train_end:val_end].copy(),
        df.iloc[val_end:].copy(),
    )


def _train_models(
    full_df: pd.DataFrame,
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
    test_df: pd.DataFrame,
    work_dir: Path,
    cfg: TrainingConfig,
    store_id: str,
    date_tag: str,
    hpo_params: dict[str, Any] | None = None,
) -> tuple[Path, Path, lgb.LGBMRegressor, lgb.LGBMRegressor, pd.DataFrame, dict[str, float], dict[str, float]]:
    """train/val/test はあらかじめ呼び出し側で _time_series_split_3 して渡す（この
    関数内では分割しない）。early-stopping の評価は val_df のみに対して行い、
    test_df はここでは一切フィッティング/評価に使わない ── 呼び出し側が
    _log_metrics_by_store(test_df, ...) で最初に触れる「未見データ」のまま渡す。
    """
    x_train = train_df[FEATURE_COLUMNS]
    y_men_train = train_df["men"].astype(float)
    y_women_train = train_df["women"].astype(float)
    weights = _sample_weights(train_df, cfg)

    x_val = val_df[FEATURE_COLUMNS]
    y_men_val = val_df["men"].astype(float)
    y_women_val = val_df["women"].astype(float)

    extra = dict(hpo_params) if hpo_params else {}
    callbacks = [lgb.early_stopping(15, verbose=False), lgb.log_evaluation(0)]
    # train のみでフィットし、val のみで early-stop を判定する（test は不可視のまま）
    model_men = _build_lgb_model(objective=cfg.objective, **extra)
    model_women = _build_lgb_model(objective=cfg.objective, **extra)
    model_men.fit(
        x_train, y_men_train, sample_weight=weights,
        eval_set=[(x_val, y_men_val)], callbacks=callbacks,
    )
    model_women.fit(
        x_train, y_women_train, sample_weight=weights,
        eval_set=[(x_val, y_women_val)], callbacks=callbacks,
    )
    best_men_rounds = model_men.best_iteration_ if model_men.best_iteration_ > 0 else model_men.n_estimators
    best_women_rounds = model_women.best_iteration_ if model_women.best_iteration_ > 0 else model_women.n_estimators
    print(f"[train-ml][early_stop] store={store_id} best_rounds men={best_men_rounds} women={best_women_rounds}")

    # 本番用モデルは train+val+test の全データで再学習する（サービング用途なので
    # 直近データも含めて最大限活用してよい。リークが問題になるのは「評価」であって
    # 「本番モデルの学習データ量」ではない）。ハイパラ/ラウンド数は val で選んだもの。
    full_weights = _sample_weights(full_df, cfg)
    prod_model_men = _build_lgb_model(objective=cfg.objective, n_estimators=best_men_rounds, **extra)
    prod_model_women = _build_lgb_model(objective=cfg.objective, n_estimators=best_women_rounds, **extra)
    prod_model_men.fit(full_df[FEATURE_COLUMNS], full_df["men"].astype(float), sample_weight=full_weights)
    prod_model_women.fit(full_df[FEATURE_COLUMNS], full_df["women"].astype(float), sample_weight=full_weights)

    # LightGBM は .txt 形式で保存（XGBoost の .json より軽量）
    model_men_path = work_dir / f"model_{store_id}_{date_tag}_men.txt"
    model_women_path = work_dir / f"model_{store_id}_{date_tag}_women.txt"
    prod_model_men.booster_.save_model(str(model_men_path))
    prod_model_women.booster_.save_model(str(model_women_path))

    # Feature importance (from production models trained on full data)
    fi_men = dict(zip(FEATURE_COLUMNS, prod_model_men.feature_importances_.tolist()))
    fi_women = dict(zip(FEATURE_COLUMNS, prod_model_women.feature_importances_.tolist()))

    # 報告用メトリクスは train/val に一切触れていない model_men/model_women
    # （train-only + val-early-stop）で test_df を評価することで得る。
    return model_men_path, model_women_path, model_men, model_women, test_df, fi_men, fi_women


def _rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.sqrt(np.mean((y_pred - y_true) ** 2)))


def _seasonal_naive_metrics(df: pd.DataFrame) -> dict[str, float]:
    """Seasonal-naive baseline the ML must beat: predict tonight's `total` as the
    same weekday + same time-slot from LAST week. Reuses the existing
    `same_dow_last_week_total` feature (median-filled where last week's slot is
    missing), so it is the realistic "last week, same time" rule with no model.
    Returned MAE/RMSE are stored next to the model's metrics so the owner can see
    whether the 24-feature, daily-retrained pipeline actually earns its complexity.
    """
    if "same_dow_last_week_total" not in df.columns or "total" not in df.columns:
        return {}
    pred_total = pd.to_numeric(df["same_dow_last_week_total"], errors="coerce").to_numpy()
    true_total = pd.to_numeric(df["total"], errors="coerce").to_numpy()
    mask = ~(np.isnan(pred_total) | np.isnan(true_total))
    if not mask.any():
        return {}
    pred_total = pred_total[mask]
    true_total = true_total[mask]
    return {
        "total_mae": float(np.mean(np.abs(pred_total - true_total))),
        "total_rmse": _rmse(true_total, pred_total),
        "rows_scored": int(mask.sum()),
    }


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


def _daily_accuracy(
    sdf: pd.DataFrame, pred_men: np.ndarray, pred_women: np.ndarray,
) -> list[dict[str, Any]]:
    """Compute per-date MAE within a store's test data."""
    if sdf.empty or "ts" not in sdf.columns:
        return []
    sdf = sdf.copy()
    sdf["_pred_total"] = np.maximum(pred_men, 0.0) + np.maximum(pred_women, 0.0)
    sdf["_date"] = sdf["ts"].dt.date.astype(str)
    daily = []
    for dt, g in sdf.groupby("_date"):
        true_t = g["total"].astype(float).to_numpy()
        pred_t = g["_pred_total"].to_numpy()
        daily.append({
            "date": str(dt),
            "rows": int(len(g)),
            "total_mae": round(float(np.mean(np.abs(pred_t - true_t))), 2),
        })
    return sorted(daily, key=lambda x: x["date"])


def _log_metrics_by_store(
    test_df: pd.DataFrame, model_men: lgb.LGBMRegressor, model_women: lgb.LGBMRegressor,
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
        daily = _daily_accuracy(sdf, pred_men_all[idx], pred_women_all[idx])
        baseline = _seasonal_naive_metrics(sdf)
        entry = {
            "store_id": store,
            "rows_test": int(len(sdf)),
            "overall": overall,
            "weekend_night_segment_rows": int(peak_mask.sum()),
            "weekend_night_segment": segment,
            # train/val に一切触れていない、真に未見のホールドアウト test（既定15%）
            "evaluation": "holdout_test_15pct_3way_split",
            "daily_accuracy": daily,
        }
        if baseline:
            entry["baseline_seasonal_naive"] = baseline
            b_mae = baseline.get("total_mae")
            m_mae = overall.get("total_mae")
            if b_mae and b_mae > 0 and m_mae is not None:
                # >0 means the ML beats "last week same slot"; <=0 means it does not.
                entry["ml_vs_baseline_total_mae_improvement_pct"] = round(
                    (b_mae - m_mae) / b_mae * 100.0, 1
                )
        print("[train-ml][metrics]", json.dumps(entry, ensure_ascii=True))
        all_metrics[store] = entry
    return all_metrics


def _filter_allowed_stores(store_ids: list[str], allow_list: set[str]) -> tuple[list[str], list[str]]:
    """Split ``store_ids`` (found in the fetched training data) into those present
    in the active-store allow-list (``oriental/utils/stores.ALL_STORE_IDS``) and
    those that are not (closed/dead/unknown store_ids that must never be retrained
    just because a stray row exists for them)."""
    allowed = [s for s in store_ids if s in allow_list]
    rejected = [s for s in store_ids if s not in allow_list]
    return allowed, rejected


def _is_stale_store(last_ts: "pd.Timestamp", now: "pd.Timestamp", stale_days: float) -> bool:
    """True if a store's most recent training row is older than ``stale_days``
    days relative to ``now`` (e.g. a store that stopped reporting/closed)."""
    age_days = (now - last_ts).total_seconds() / 86400.0
    return age_days > stale_days


def _gate_decision(
    new_mae: float | None,
    old_mae: float | None,
    max_regression_pct: float,
) -> tuple[str, str]:
    """Champion/challenger gate for a single store's new (challenger) model vs. the
    currently-deployed (champion) model, compared by held-out test total_mae.

    Returns ``(decision, reason)`` where ``decision`` is ``"replaced"`` (upload the
    new model) or ``"skipped"`` (keep serving the existing model). Missing/invalid
    old metrics (first run, or old entry had no comparable MAE) always resolve to
    ``"replaced"`` since there is nothing safe to gate against.
    """
    if old_mae is None or new_mae is None or old_mae <= 0:
        return "replaced", "no_prior_metrics"
    regression_pct = (new_mae - old_mae) / old_mae * 100.0
    if regression_pct > max_regression_pct:
        return "skipped", (
            f"new_mae={new_mae:.4f} old_mae={old_mae:.4f} "
            f"regression_pct={regression_pct:.1f}>{max_regression_pct:.1f}"
        )
    return "replaced", (
        f"new_mae={new_mae:.4f} old_mae={old_mae:.4f} regression_pct={regression_pct:.1f}"
    )


def _reused_hpo_params(existing_metrics: dict[str, Any], store_id: str) -> dict[str, Any]:
    """When Optuna is disabled (daily fixed-param retrain), reuse the per-store
    ``hpo_params`` the weekly Optuna run previously wrote into the deployed
    metadata, instead of always falling back to fixed defaults. Returns {} if no
    usable tuned params exist (first run, or store never went through Optuna)."""
    entry = existing_metrics.get(store_id) if isinstance(existing_metrics, dict) else None
    if not isinstance(entry, dict):
        return {}
    params = entry.get("hpo_params")
    return dict(params) if isinstance(params, dict) and params else {}


def _carry_forward_store(
    store_id: str,
    reason: str,
    *,
    existing_store_models: dict[str, Any],
    existing_metrics: dict[str, Any],
    store_models: dict[str, Any],
    all_metrics: dict[str, Any],
    gate_decisions: list[dict[str, Any]],
) -> None:
    """Carry forward a store's existing (already-deployed) model/metrics entries
    unchanged, because this run intentionally skipped it (allow-list, stale-store
    guard, gate regression, insufficient rows, ...) or never saw it at all. The
    carried-forward ``store_models`` entry keeps pointing at whatever model files
    were uploaded by a PRIOR run — since uploads never delete old files (x-upsert
    only adds/overwrites the SAME name), those files remain valid in storage.
    """
    old_sm = existing_store_models.get(store_id)
    if isinstance(old_sm, dict):
        store_models[store_id] = dict(old_sm)
    old_entry = existing_metrics.get(store_id)
    if isinstance(old_entry, dict):
        carried = dict(old_entry)
        carried["gate_skipped"] = True
        carried["gate_reason"] = reason
        all_metrics[store_id] = carried
    gate_decisions.append({"store_id": store_id, "decision": "skipped", "reason": reason})


def _coverage_stats(
    df: pd.DataFrame, requested_days: int, train_limit: int, rows_fetched: int,
) -> dict[str, Any]:
    """Coverage visibility (c): how much history did this run actually train on,
    vs. what was requested — and did the row LIMIT (not the day window) silently
    cut the window short? ``row_limit_hit`` mirrors the exact symptom that caused
    the July regression: ``rows_fetched == train_limit`` with a much smaller
    ``effective_days`` than ``requested_days``.
    """
    stats: dict[str, Any] = {
        "requested_days": requested_days,
        "total_rows": int(rows_fetched),
        "row_limit_hit": bool(rows_fetched >= train_limit),
    }
    if df.empty or "ts" not in df.columns:
        stats.update({"oldest_ts": None, "newest_ts": None, "effective_days": 0.0})
        return stats
    oldest = df["ts"].min()
    newest = df["ts"].max()
    effective_days = (newest - oldest).total_seconds() / 86400.0
    stats.update({
        "oldest_ts": oldest.isoformat(),
        "newest_ts": newest.isoformat(),
        "effective_days": round(float(effective_days), 2),
    })
    return stats


def _write_github_step_summary(
    coverage: dict[str, Any], gate_decisions: list[dict[str, Any]],
) -> None:
    """Append a human-readable coverage + gate-decision table to the GitHub
    Actions job summary (no-op outside GHA / when GITHUB_STEP_SUMMARY is unset)."""
    path = os.getenv("GITHUB_STEP_SUMMARY")
    if not path:
        return
    lines = ["## Train ML model — summary", ""]
    lines.append(f"- requested_days: {coverage.get('requested_days')}")
    lines.append(f"- effective_days: {coverage.get('effective_days')}")
    lines.append(f"- total_rows: {coverage.get('total_rows')}")
    lines.append(f"- row_limit_hit: {coverage.get('row_limit_hit')}")
    lines.append(f"- oldest_ts: {coverage.get('oldest_ts')}")
    lines.append(f"- newest_ts: {coverage.get('newest_ts')}")
    lines.append("")
    lines.append("| store_id | decision | reason |")
    lines.append("|---|---|---|")
    for d in gate_decisions:
        lines.append(f"| {d.get('store_id')} | {d.get('decision')} | {d.get('reason', '')} |")
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except OSError as exc:  # noqa: BLE001 - best-effort, never fail the run over this
        print(f"[train-ml][summary] could not write GITHUB_STEP_SUMMARY: {exc}")


def _build_metadata(
    cfg: TrainingConfig,
    df: pd.DataFrame,
    *,
    trained_at: str,
    date_tag: str,
    store_models: dict[str, dict[str, Any]],
    metrics: dict[str, dict[str, Any]] | None = None,
    coverage: dict[str, Any] | None = None,
    gate_decisions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "schema_version": cfg.schema_version,
        "feature_columns": FEATURE_COLUMNS,
        "model_men": "model_men.txt",
        "model_women": "model_women.txt",
        "model_format": "lightgbm",
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
        "recency_halflife_days": cfg.recency_halflife_days,
        "recency_floor": cfg.recency_floor,
        "gate_max_regression_pct": cfg.gate_max_regression_pct,
        "stale_store_days": cfg.stale_store_days,
        "objective": cfg.objective,
        "python_version": platform.python_version(),
        "xgboost_version": xgb.__version__,
    }
    if metrics:
        meta["metrics"] = metrics
    if coverage:
        # Task (c): coverage visibility, both as a nested detail block and as the
        # specifically-named top-level fields the audit asked to track.
        meta["coverage"] = coverage
        meta["requested_days"] = coverage.get("requested_days")
        meta["effective_days"] = coverage.get("effective_days")
        meta["row_limit_hit"] = coverage.get("row_limit_hit")
    if gate_decisions is not None:
        meta["gate_decisions"] = gate_decisions
    return meta


def _upload_file(
    *,
    cfg: TrainingConfig,
    session: requests.Session,
    local_path: Path,
    remote_name: str,
    content_type: str,
    max_retries: int = 3,
) -> None:
    object_path = f"{cfg.prefix}/{remote_name}".strip("/")
    endpoint = f"{cfg.supabase_url}/storage/v1/object/{cfg.bucket}/{object_path}"
    headers = {
        "apikey": cfg.supabase_service_key,
        "Authorization": f"Bearer {cfg.supabase_service_key}",
        "x-upsert": "true",
        "Content-Type": content_type,
    }
    data = local_path.read_bytes()
    last_err = ""
    for attempt in range(1, max_retries + 1):
        try:
            response = session.post(endpoint, headers=headers, data=data, timeout=30)
            if response.ok:
                return
            last_err = f"status={response.status_code} body={response.text[:200]}"
            if response.status_code < 500 and response.status_code != 400:
                break  # 4xx (except 400) は再試行しない
        except Exception as exc:
            last_err = str(exc)[:200]
        if attempt < max_retries:
            wait = 5 * attempt
            print(f"[train-ml] upload retry {attempt}/{max_retries} for {remote_name} (wait {wait}s): {last_err}")
            time.sleep(wait)
    raise SystemExit(f"upload failed after {max_retries} attempts: {remote_name} {last_err}")


def _download_existing_metadata(cfg: TrainingConfig, session: requests.Session) -> dict[str, Any] | None:
    """Fetch the current (deployed) metadata.json from Storage. Used for: the
    champion/challenger gate's prior per-store MAE, per-store hpo_params reuse on
    Optuna-disabled runs, and carrying forward any store this run skips/doesn't
    touch (subset training, allow-list, stale-store guard, gate rejection)."""
    object_path = f"{cfg.prefix}/metadata.json".strip("/")
    endpoint = f"{cfg.supabase_url}/storage/v1/object/{cfg.bucket}/{object_path}"
    headers = {"apikey": cfg.supabase_service_key, "Authorization": f"Bearer {cfg.supabase_service_key}"}
    try:
        resp = session.get(endpoint, headers=headers, timeout=30)
        if resp.ok:
            data = resp.json()
            return data if isinstance(data, dict) else None
    except Exception as exc:  # noqa: BLE001
        print(f"[train-ml][merge] could not fetch existing metadata: {str(exc)[:120]}")
    return None


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

    coverage = _coverage_stats(df, cfg.train_days, cfg.train_limit, len(rows))
    print("[train-ml][coverage]", json.dumps(coverage, ensure_ascii=True))

    # Download the currently-deployed metadata ONCE, up front. It feeds three
    # things: the champion/challenger gate (b's prior per-store test MAE), HPO
    # param reuse on Optuna-disabled (daily) runs, and carry-forward of any store
    # this run intentionally skips or never touches — so metadata.json always
    # stays complete/valid for every store still being served.
    existing_meta = _download_existing_metadata(cfg, session)
    if existing_meta and str(existing_meta.get("schema_version")) == cfg.schema_version:
        existing_store_models = existing_meta.get("store_models")
        existing_store_models = existing_store_models if isinstance(existing_store_models, dict) else {}
        existing_metrics = existing_meta.get("metrics")
        existing_metrics = existing_metrics if isinstance(existing_metrics, dict) else {}
    else:
        if existing_meta:
            print(
                f"[train-ml][merge] existing metadata schema "
                f"({existing_meta.get('schema_version')}) != {cfg.schema_version}; ignoring for gate/carry-forward"
            )
        existing_store_models = {}
        existing_metrics = {}

    store_models: dict[str, dict[str, Any]] = {}
    all_metrics: dict[str, dict[str, Any]] = {}
    gate_decisions: list[dict[str, Any]] = []
    replaced_stores: list[str] = []

    def _carry_forward(store_id: str, reason: str) -> None:
        _carry_forward_store(
            store_id,
            reason,
            existing_store_models=existing_store_models,
            existing_metrics=existing_metrics,
            store_models=store_models,
            all_metrics=all_metrics,
            gate_decisions=gate_decisions,
        )

    with tempfile.TemporaryDirectory(prefix="train-ml-") as tmp:
        work_dir = Path(tmp)
        stores_in_data = [cfg.store_id] if cfg.store_id else sorted(df["store_id"].dropna().unique().tolist())
        if not stores_in_data:
            raise SystemExit("no store_id available for per-store training")

        # Active-store allow-list (b): only ever (re)train stores Oriental/Aisekiya
        # still actively serves. A stray row for a closed store must not resurrect it.
        allowed_stores, rejected_stores = _filter_allowed_stores(stores_in_data, set(ALL_STORE_IDS))
        for sid in rejected_stores:
            print(f"[train-ml][skip] store_id={sid} not in ALL_STORE_IDS allow-list")
            _carry_forward(sid, "not_in_allowlist")

        # Stale-store guard (b): a store can be in the allow-list yet have stopped
        # reporting (e.g. temporarily/permanently closed) — skip retraining it on
        # data that no longer reflects reality.
        now_ts = pd.Timestamp.now(tz=cfg.timezone)
        trainable_stores: list[str] = []
        for sid in allowed_stores:
            sdf_ts = df.loc[df["store_id"] == sid, "ts"]
            if sdf_ts.empty:
                continue
            last_ts = sdf_ts.max()
            if _is_stale_store(last_ts, now_ts, cfg.stale_store_days):
                print(f"[train-ml][skip] stale-store skip: {sid} last={last_ts.date()}")
                _carry_forward(sid, f"stale_store last={last_ts.date()}")
            else:
                trainable_stores.append(sid)

        for store_id in trainable_stores:
            sdf = df[df["store_id"] == store_id].copy().reset_index(drop=True)
            if len(sdf) < 200:
                print(f"[train-ml][skip] store_id={store_id} rows={len(sdf)} (<200)")
                _carry_forward(store_id, "insufficient_rows")
                continue

            # 評価方法のリーク対策（#4）: train/val/test に3分割し、
            # HPO（Optuna）と early-stopping は train+val のみで完結させる。
            # test は _log_metrics_by_store に渡すまで一切参照しない「未見データ」。
            train_part, val_part, test_part = _time_series_split_3(sdf)

            # HPO param source (d): weekly Optuna runs re-tune fresh; daily fixed-
            # param runs reuse the weekly-tuned params from deployed metadata (if
            # any) instead of always falling back to the fixed defaults.
            if cfg.optuna_enabled:
                hpo_params = _optimize_params(train_part, val_part, cfg, store_id)
                hpo_source = "optuna" if hpo_params else "defaults"
            else:
                hpo_params = _reused_hpo_params(existing_metrics, store_id)
                hpo_source = "reused_weekly_optuna" if hpo_params else "defaults"
            print(
                f"[train-ml][hpo] store={store_id} source={hpo_source} "
                f"params={json.dumps(hpo_params, ensure_ascii=True)}"
            )

            model_men_path, model_women_path, model_men, model_women, test_df, fi_men, fi_women = _train_models(
                sdf, train_part, val_part, test_part, work_dir, cfg, store_id, date_tag, hpo_params=hpo_params,
            )
            store_metrics = _log_metrics_by_store(test_df, model_men, model_women)
            new_entry = store_metrics.get(store_id)
            if new_entry is None:
                print(f"[train-ml][skip] store_id={store_id} produced no test metrics; keeping existing model")
                _carry_forward(store_id, "no_test_metrics")
                continue
            if hpo_params:
                new_entry["hpo_params"] = hpo_params
            new_entry["hpo_params_source"] = hpo_source
            new_entry["feature_importance_men"] = fi_men
            new_entry["feature_importance_women"] = fi_women

            # Champion/challenger gate (a): compare the new (challenger) model's
            # held-out test total_mae against the currently-deployed (champion)
            # model's. Only upload if it doesn't regress by more than the threshold.
            new_mae = (new_entry.get("overall") or {}).get("total_mae")
            old_entry = existing_metrics.get(store_id)
            old_entry = old_entry if isinstance(old_entry, dict) else None
            old_mae = (old_entry.get("overall") or {}).get("total_mae") if old_entry else None
            decision, reason = _gate_decision(new_mae, old_mae, cfg.gate_max_regression_pct)
            gate_decisions.append({
                "store_id": store_id, "decision": decision, "reason": reason,
                "new_mae": new_mae, "old_mae": old_mae,
            })
            print(f"[train-ml][gate] store={store_id} decision={decision} reason={reason}")

            if decision == "skipped":
                # Challenger regressed too much — keep serving the deployed champion
                # by carrying forward its old metadata entry (old model files are
                # left untouched in storage, so the carried-forward paths stay valid).
                if old_entry is not None:
                    carried = dict(old_entry)
                    carried["gate_skipped"] = True
                    carried["gate_reason"] = reason
                    carried["challenger_mae"] = new_mae
                    all_metrics[store_id] = carried
                if store_id in existing_store_models:
                    store_models[store_id] = dict(existing_store_models[store_id])
                continue

            new_entry["gate_skipped"] = False
            all_metrics[store_id] = new_entry
            replaced_stores.append(store_id)

            # Latest alias for simpler rollback/fallback
            alias_men_path = work_dir / f"model_{store_id}_men.txt"
            alias_women_path = work_dir / f"model_{store_id}_women.txt"
            alias_men_path.write_bytes(model_men_path.read_bytes())
            alias_women_path.write_bytes(model_women_path.read_bytes())

            for p in (model_men_path, model_women_path, alias_men_path, alias_women_path):
                _upload_file(
                    cfg=cfg,
                    session=session,
                    local_path=p,
                    remote_name=p.name,
                    content_type="text/plain",
                )
            store_models[store_id] = {
                "model_men": alias_men_path.name,
                "model_women": alias_women_path.name,
                "dated_model_men": model_men_path.name,
                "dated_model_women": model_women_path.name,
                "row_count": int(len(sdf)),
                "trained_at": trained_at,
            }

        # Completeness (task 1/6): carry forward any store this run never touched
        # at all (e.g. zero rows in the fetch window) so metadata.json stays valid
        # for every store still being served, not just the ones processed above.
        for sid, old_sm in existing_store_models.items():
            if sid in store_models:
                continue
            store_models[sid] = dict(old_sm)
            gate_decisions.append({"store_id": sid, "decision": "carried_forward", "reason": "no_data_this_run"})
            old_entry = existing_metrics.get(sid)
            if isinstance(old_entry, dict) and sid not in all_metrics:
                carried = dict(old_entry)
                carried.setdefault("gate_skipped", True)
                carried.setdefault("gate_reason", "no_data_this_run")
                all_metrics[sid] = carried

        if not store_models:
            raise SystemExit("no per-store models were trained or carried forward (all stores skipped)")

        gate_summary = {
            "replaced": sum(1 for d in gate_decisions if d["decision"] == "replaced"),
            "skipped": sum(1 for d in gate_decisions if d["decision"] == "skipped"),
            "carried_forward": sum(1 for d in gate_decisions if d["decision"] == "carried_forward"),
        }
        print("[train-ml][gate][summary]", json.dumps(gate_summary, ensure_ascii=True))
        print("[train-ml][gate][decisions]", json.dumps(gate_decisions, ensure_ascii=True))

        metadata = _build_metadata(
            cfg,
            df,
            trained_at=trained_at,
            date_tag=date_tag,
            store_models=store_models,
            metrics=all_metrics if all_metrics else None,
            coverage=coverage,
            gate_decisions=gate_decisions,
        )
        metadata_path = work_dir / "metadata.json"
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")

        # backward compatibility global aliases: only pick a default store from
        # among the stores actually (re)trained+uploaded THIS run — carried-forward
        # stores have no local files in work_dir (their models already live in
        # storage from a prior run, untouched).
        if cfg.store_id and cfg.store_id in replaced_stores:
            default_store = cfg.store_id
        elif replaced_stores:
            default_store = sorted(replaced_stores)[0]
        else:
            default_store = None

        if default_store is not None:
            default_men = work_dir / store_models[default_store]["model_men"]
            default_women = work_dir / store_models[default_store]["model_women"]
            global_men = work_dir / "model_men.txt"
            global_women = work_dir / "model_women.txt"
            global_men.write_bytes(default_men.read_bytes())
            global_women.write_bytes(default_women.read_bytes())
            _upload_file(
                cfg=cfg,
                session=session,
                local_path=global_men,
                remote_name=global_men.name,
                content_type="text/plain",
            )
            _upload_file(
                cfg=cfg,
                session=session,
                local_path=global_women,
                remote_name=global_women.name,
                content_type="text/plain",
            )
        else:
            print(
                "[train-ml] no store was (re)trained this run (all gated/stale/allow-list skipped); "
                "leaving existing global model_men.txt/model_women.txt untouched"
            )
        _upload_file(
            cfg=cfg,
            session=session,
            local_path=metadata_path,
            remote_name="metadata.json",
            content_type="application/json",
        )

    _write_github_step_summary(coverage, gate_decisions)

    print(
        "[train-ml] uploaded models successfully",
        json.dumps(
            {
                "bucket": cfg.bucket,
                "prefix": cfg.prefix,
                "schema_version": cfg.schema_version,
                "row_count": len(df),
                "stores_served": sorted(store_models.keys()),
                "stores_replaced": sorted(replaced_stores),
                "gate_summary": gate_summary,
            },
            ensure_ascii=True,
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
