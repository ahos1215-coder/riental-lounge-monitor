from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from oriental.ml.model_registry import ForecastModelRegistry
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
    train_days: int
    train_limit: int
    bucket: str
    prefix: str
    schema_version: str
    cache_dir: Path

    @classmethod
    def from_env(cls) -> "Cfg":
        return cls(
            supabase_url=os.getenv("SUPABASE_URL", "").strip().rstrip("/"),
            supabase_service_key=(
                os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
                or os.getenv("SUPABASE_SERVICE_KEY", "").strip()
            ),
            timezone=os.getenv("TIMEZONE", "Asia/Tokyo").strip(),
            train_days=int(os.getenv("ML_TRAIN_DAYS", "180")),
            train_limit=int(os.getenv("ML_TRAIN_LIMIT", "120000")),
            bucket=os.getenv("FORECAST_MODEL_BUCKET", "ml-models").strip(),
            prefix=os.getenv("FORECAST_MODEL_PREFIX", "forecast/latest").strip("/"),
            schema_version=os.getenv("FORECAST_MODEL_SCHEMA_VERSION", "v1").strip(),
            cache_dir=Path(os.getenv("FORECAST_MODEL_CACHE_DIR", "data/ml_models")),
        )

    def validate(self) -> None:
        if not self.supabase_url or not self.supabase_service_key:
            raise SystemExit("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY/SUPABASE_SERVICE_KEY are required")


def _fetch_rows(cfg: Cfg, session: requests.Session) -> list[dict[str, Any]]:
    endpoint = f"{cfg.supabase_url}/rest/v1/logs"
    end_ts = datetime.now(timezone.utc)
    start_ts = end_ts - timedelta(days=max(1, cfg.train_days))
    page_size = 1000
    rows: list[dict[str, Any]] = []
    start = 0

    while len(rows) < cfg.train_limit:
        end = min(start + page_size - 1, cfg.train_limit - 1)
        params: list[tuple[str, str]] = [
            ("select", "store_id,ts,men,women,total,weather_code,temp_c,precip_mm"),
            ("order", "ts.asc"),
            ("limit", str(page_size)),
            ("offset", str(start)),
            ("ts", f"gte.{start_ts.isoformat()}"),
            ("ts", f"lte.{end_ts.isoformat()}"),
            ("men", "not.is.null"),
            ("women", "not.is.null"),
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
            raise SystemExit(f"failed to fetch logs: status={resp.status_code} body={resp.text[:200]}")
        payload = resp.json()
        if not isinstance(payload, list):
            raise SystemExit("invalid logs payload")
        chunk = [x for x in payload if isinstance(x, dict)]
        rows.extend(chunk)
        print(f"[fetch] {len(rows)}/{cfg.train_limit} rows fetched...")
        if len(chunk) < page_size:
            break
        start += page_size

    return rows[: cfg.train_limit]


def _permutation_pvalue(a: np.ndarray, b: np.ndarray, rounds: int = 3000) -> float:
    if len(a) < 2 or len(b) < 2:
        return 1.0
    max_n = 5000
    if len(a) > max_n:
        rng_a = np.random.default_rng(42)
        a = rng_a.choice(a, size=max_n, replace=False)
    if len(b) > max_n:
        rng_b = np.random.default_rng(43)
        b = rng_b.choice(b, size=max_n, replace=False)
    rounds = min(rounds, 1000)
    obs = abs(a.mean() - b.mean())
    merged = np.concatenate([a, b])
    n_a = len(a)
    count = 0
    rng = random.Random(42)
    merged_list = merged.tolist()
    for _ in range(rounds):
        rng.shuffle(merged_list)
        sa = np.array(merged_list[:n_a], dtype=float)
        sb = np.array(merged_list[n_a:], dtype=float)
        if abs(sa.mean() - sb.mean()) >= obs:
            count += 1
    return (count + 1) / (rounds + 1)


def _payday_analysis(df: pd.DataFrame) -> dict[str, Any]:
    local_date = df["ts"].dt.date
    day = pd.to_datetime(local_date).dt.day
    payday_rows = df[df["is_payday_week"] == 1]["total"].astype(float).to_numpy()
    pre_rows = df[day.isin([22, 23, 24])]["total"].astype(float).to_numpy()
    pval = _permutation_pvalue(payday_rows, pre_rows)
    return {
        "payday_count": int(len(payday_rows)),
        "pre_count": int(len(pre_rows)),
        "payday_mean_total": float(np.mean(payday_rows)) if len(payday_rows) else None,
        "pre_22_24_mean_total": float(np.mean(pre_rows)) if len(pre_rows) else None,
        "diff_payday_minus_pre": (
            float(np.mean(payday_rows) - np.mean(pre_rows)) if len(payday_rows) and len(pre_rows) else None
        ),
        "permutation_pvalue": float(pval),
    }


def _last_train_window_analysis(df: pd.DataFrame) -> pd.DataFrame:
    out: list[dict[str, Any]] = []
    for store_id, g in df.groupby("store_id", dropna=False):
        h = g.copy()
        h["hhmm"] = h["ts"].dt.hour * 100 + h["ts"].dt.minute
        pre = h[(h["hhmm"] >= 2230) & (h["hhmm"] <= 2255)]["total"].astype(float)
        last_train = h[(h["hhmm"] >= 2300) & (h["hhmm"] <= 2345)]["total"].astype(float)
        early = h[(h["hhmm"] >= 2200) & (h["hhmm"] <= 2225)]["total"].astype(float)
        slope = None
        if len(last_train) >= 3:
            x = np.arange(len(last_train), dtype=float)
            slope = float(np.polyfit(x, last_train.to_numpy(), 1)[0])
        out.append(
            {
                "store_id": store_id,
                "mean_22_00_22_25": float(early.mean()) if len(early) else None,
                "mean_22_30_22_55": float(pre.mean()) if len(pre) else None,
                "mean_23_00_23_45": float(last_train.mean()) if len(last_train) else None,
                "delta_23_minus_22_30": (
                    float(last_train.mean() - pre.mean()) if len(last_train) and len(pre) else None
                ),
                "slope_23_window": slope,
                "is_decreasing_in_23_window": bool(slope is not None and slope < 0),
                "looks_decrease_from_22_30": bool(len(last_train) and len(pre) and (last_train.mean() < pre.mean())),
                "looks_decrease_from_22_00": bool(len(last_train) and len(early) and (last_train.mean() < early.mean())),
            }
        )
    return pd.DataFrame(out).sort_values("delta_23_minus_22_30", na_position="last")


def _predict_error(df: pd.DataFrame, cfg: Cfg) -> pd.DataFrame:
    registry = ForecastModelRegistry(
        supabase_url=cfg.supabase_url,
        service_role_key=cfg.supabase_service_key,
        bucket=cfg.bucket,
        model_prefix=cfg.prefix,
        cache_dir=cfg.cache_dir,
        refresh_sec=300,
        schema_version=cfg.schema_version,
        logger=logging.getLogger("validate-features"),
    )
    bundle = registry.get_bundle()
    x = df[FEATURE_COLUMNS]
    men_pred, women_pred = bundle.model.predict(x)
    out = df.copy()
    out["pred_total"] = np.maximum(men_pred, 0) + np.maximum(women_pred, 0)
    out["abs_err"] = (out["pred_total"] - out["total"].astype(float)).abs()
    return out


def _weather_switch_error_analysis(df_pred: pd.DataFrame) -> dict[str, Any]:
    d = df_pred.copy()
    d["is_rain"] = (pd.to_numeric(d["weather_code"], errors="coerce").fillna(-1) >= 51).astype(int)
    d = d.sort_values(["store_id", "ts"])
    d["prev_is_rain"] = d.groupby("store_id", dropna=False)["is_rain"].shift(1)
    switches = d[(d["prev_is_rain"].notna()) & (d["prev_is_rain"] != d["is_rain"])].copy()
    if switches.empty:
        return {"switch_count": 0}

    before_abs: list[float] = []
    after_abs: list[float] = []
    before_sq: list[float] = []
    after_sq: list[float] = []
    for _, sw in switches.iterrows():
        sid = sw["store_id"]
        ts = sw["ts"]
        g = d[d["store_id"] == sid]
        before = g[(g["ts"] >= ts - pd.Timedelta(minutes=30)) & (g["ts"] < ts)]
        after = g[(g["ts"] > ts) & (g["ts"] <= ts + pd.Timedelta(minutes=30))]
        if len(before):
            e = (before["pred_total"] - before["total"].astype(float)).astype(float)
            before_abs.extend(e.abs().tolist())
            before_sq.extend((e * e).tolist())
        if len(after):
            e = (after["pred_total"] - after["total"].astype(float)).astype(float)
            after_abs.extend(e.abs().tolist())
            after_sq.extend((e * e).tolist())
    a = np.array(before_abs, dtype=float)
    b = np.array(after_abs, dtype=float)
    pval_mae = _permutation_pvalue(a, b)
    before_rmse = float(np.sqrt(np.mean(before_sq))) if before_sq else None
    after_rmse = float(np.sqrt(np.mean(after_sq))) if after_sq else None
    return {
        "switch_count": int(len(switches)),
        "before_n": int(len(a)),
        "after_n": int(len(b)),
        "before_mae": float(a.mean()) if len(a) else None,
        "after_mae": float(b.mean()) if len(b) else None,
        "delta_mae_after_minus_before": float(b.mean() - a.mean()) if len(a) and len(b) else None,
        "before_rmse": before_rmse,
        "after_rmse": after_rmse,
        "delta_rmse_after_minus_before": (
            float(after_rmse - before_rmse) if (before_rmse is not None and after_rmse is not None) else None
        ),
        "permutation_pvalue_mae": float(pval_mae),
    }


def _low_importance_features(cfg: Cfg) -> dict[str, Any]:
    registry = ForecastModelRegistry(
        supabase_url=cfg.supabase_url,
        service_role_key=cfg.supabase_service_key,
        bucket=cfg.bucket,
        model_prefix=cfg.prefix,
        cache_dir=cfg.cache_dir,
        refresh_sec=300,
        schema_version=cfg.schema_version,
        logger=logging.getLogger("validate-features"),
    )
    bundle = registry.get_bundle()
    men = bundle.model.model_men.get_booster().get_score(importance_type="gain")
    women = bundle.model.model_women.get_booster().get_score(importance_type="gain")
    fmap = {f"f{i}": col for i, col in enumerate(FEATURE_COLUMNS)}

    def mapped(score: dict[str, float]) -> dict[str, float]:
        return {fmap.get(k, k): float(v) for k, v in score.items()}

    m = mapped(men)
    w = mapped(women)
    rows = []
    for col in FEATURE_COLUMNS:
        mg = m.get(col, 0.0)
        wg = w.get(col, 0.0)
        rows.append({"feature": col, "men_gain": mg, "women_gain": wg, "avg_gain": (mg + wg) / 2.0})
    df = pd.DataFrame(rows).sort_values("avg_gain")
    return {
        "low_importance_top10": df.head(10).to_dict(orient="records"),
        "zero_gain_features": df[df["avg_gain"] <= 1e-12]["feature"].tolist(),
    }


def main() -> int:
    _load_env()
    parser = argparse.ArgumentParser(description="Validate engineered features against real data behavior")
    parser.add_argument("--days", type=int, help="override days")
    parser.add_argument("--limit", type=int, help="override row limit")
    args = parser.parse_args()

    cfg = Cfg.from_env()
    if args.days is not None:
        cfg.train_days = args.days
    if args.limit is not None:
        cfg.train_limit = args.limit
    cfg.validate()

    session = requests.Session()
    rows = _fetch_rows(cfg, session)
    if len(rows) < 200:
        raise SystemExit(f"not enough rows: {len(rows)}")

    df = prepare_dataframe(rows, cfg.timezone)
    if df.empty:
        raise SystemExit("empty dataframe after preprocess")

    payday = _payday_analysis(df)
    last_train = _last_train_window_analysis(df)
    pred = _predict_error(df, cfg)
    weather_shift = _weather_switch_error_analysis(pred)
    low_imp = _low_importance_features(cfg)

    out_dir = REPO_ROOT / "artifacts"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    last_train_path = out_dir / f"feature_validation_last_train_{ts}.csv"
    report_path = out_dir / f"feature_validation_report_{ts}.json"
    last_train.to_csv(last_train_path, index=False, encoding="utf-8")
    report = {
        "rows": int(len(df)),
        "payday_analysis": payday,
        "weather_switch_error_analysis": weather_shift,
        "low_importance": low_imp,
        "last_train_csv": str(last_train_path),
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("[validate] report", report_path)
    print("[validate] last_train_csv", last_train_path)
    print("[payday]", json.dumps(payday, ensure_ascii=False))
    print("[weather_switch]", json.dumps(weather_shift, ensure_ascii=False))
    print("[low_importance_top10]", json.dumps(low_imp["low_importance_top10"], ensure_ascii=False))
    print("[zero_gain_features]", json.dumps(low_imp["zero_gain_features"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
