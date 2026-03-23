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

import pandas as pd
import requests
import xgboost as xgb
from dotenv import load_dotenv
from xgboost import XGBRegressor

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


def _build_xgb_model() -> XGBRegressor:
    return XGBRegressor(
        n_estimators=100,
        max_depth=4,
        learning_rate=0.1,
        subsample=0.8,
        objective="reg:squarederror",
    )


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
            schema_version=os.getenv("FORECAST_MODEL_SCHEMA_VERSION", "v1").strip(),
            timezone=os.getenv("TIMEZONE", "Asia/Tokyo").strip(),
            train_days=_env_int("ML_TRAIN_DAYS", 180),
            train_limit=_env_int("ML_TRAIN_LIMIT", 120000),
            store_id=os.getenv("ML_TRAIN_STORE_ID", "").strip() or None,
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


def _fetch_training_rows(cfg: TrainingConfig, session: requests.Session) -> list[dict[str, Any]]:
    endpoint = f"{cfg.supabase_url}/rest/v1/logs"
    end_ts = datetime.now(timezone.utc)
    start_ts = end_ts - timedelta(days=max(1, cfg.train_days))

    params: list[tuple[str, str]] = [
        ("select", "store_id,ts,men,women,total,weather_code,temp_c"),
        ("order", "ts.asc"),
        ("limit", str(max(1, cfg.train_limit))),
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
        "Range": f"0-{max(cfg.train_limit - 1, 0)}",
    }
    response = session.get(endpoint, params=params, headers=headers, timeout=30)
    if not response.ok:
        raise SystemExit(f"failed to fetch logs from supabase: status={response.status_code}")
    payload = response.json()
    if not isinstance(payload, list):
        raise SystemExit("supabase logs payload is not a list")
    return [row for row in payload if isinstance(row, dict)]


def _train_models(df: pd.DataFrame, work_dir: Path) -> tuple[Path, Path]:
    x = df[FEATURE_COLUMNS]
    y_men = df["men"].astype(float)
    y_women = df["women"].astype(float)

    model_men = _build_xgb_model()
    model_women = _build_xgb_model()
    model_men.fit(x, y_men)
    model_women.fit(x, y_women)

    model_men_path = work_dir / "model_men.json"
    model_women_path = work_dir / "model_women.json"
    model_men.save_model(str(model_men_path))
    model_women.save_model(str(model_women_path))
    return model_men_path, model_women_path


def _build_metadata(cfg: TrainingConfig, df: pd.DataFrame) -> dict[str, Any]:
    return {
        "schema_version": cfg.schema_version,
        "feature_columns": FEATURE_COLUMNS,
        "model_men": "model_men.json",
        "model_women": "model_women.json",
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "timezone": cfg.timezone,
        "train_days": cfg.train_days,
        "train_limit": cfg.train_limit,
        "train_store_id": cfg.store_id,
        "row_count": int(len(df)),
        "python_version": platform.python_version(),
        "xgboost_version": xgb.__version__,
    }


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
    args = parser.parse_args()

    cfg = TrainingConfig.from_env()
    if args.days is not None:
        cfg.train_days = args.days
    if args.limit is not None:
        cfg.train_limit = args.limit
    if args.store_id:
        cfg.store_id = args.store_id
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

    with tempfile.TemporaryDirectory(prefix="train-ml-") as tmp:
        work_dir = Path(tmp)
        model_men_path, model_women_path = _train_models(df, work_dir)
        metadata = _build_metadata(cfg, df)
        metadata_path = work_dir / "metadata.json"
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")

        _upload_file(
            cfg=cfg,
            session=session,
            local_path=model_men_path,
            remote_name="model_men.json",
            content_type="application/json",
        )
        _upload_file(
            cfg=cfg,
            session=session,
            local_path=model_women_path,
            remote_name="model_women.json",
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
            },
            ensure_ascii=True,
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
