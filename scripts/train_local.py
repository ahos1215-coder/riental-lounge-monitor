from __future__ import annotations
import argparse, json
from pathlib import Path
import numpy as np
import pandas as pd

from oriental.ml.preprocess import prepare_dataframe, add_time_features, FEATURE_COLUMNS
from oriental.models.service import ModelService

def load_10m_json(path: Path) -> pd.DataFrame:
    obj = json.loads(path.read_text(encoding="utf-8"))
    df = pd.DataFrame(obj)
    # tsは文字列→UTC→JSTへ（preprocessの流儀に合わせる）
    df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce").dt.tz_convert("Asia/Tokyo")
    # totalが無いデータのための安全化
    if "total" not in df.columns:
        df["total"] = (df.get("men", 0) + df.get("women", 0)).astype(float)
    return df.dropna(subset=["ts"]).sort_values("ts").reset_index(drop=True)

def build_features(df: pd.DataFrame, tz: str) -> pd.DataFrame:
    # preprocessの関数で整形→特徴量付与
    base = df[["ts","men","women","total"]].copy()
    base = add_time_features(base)
    return base

def time_split_idx(n: int, val_ratio: float = 0.2):
    val = max(1, int(n * val_ratio))
    return max(1, n - val)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="in_path", required=True)
    ap.add_argument("--outdir", default="artifacts/nagasaki")
    ap.add_argument("--tz", default="Asia/Tokyo")
    args = ap.parse_args()

    in_path = Path(args.in_path)
    outdir  = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    df = load_10m_json(in_path)
    if len(df) < 60:
        raise SystemExit(f"Not enough rows: {len(df)} (need >= 60)")

    X = build_features(df, args.tz)
    # 目的変数
    y_m = df["men"].astype(float)
    y_w = df["women"].astype(float)

    cut = time_split_idx(len(df), val_ratio=0.2)
    X_tr, X_val = X.iloc[:cut], X.iloc[cut:]
    y_m_tr, y_m_val = y_m.iloc[:cut], y_m.iloc[cut:]
    y_w_tr, y_w_val = y_w.iloc[:cut], y_w.iloc[cut:]

    svc = ModelService()
    svc.fit(X_tr[FEATURE_COLUMNS], y_m_tr, y_w_tr, X_val[FEATURE_COLUMNS], y_m_val, y_w_val)
    svc.save(outdir)

    print(f"OK: trained & saved -> {outdir}")

if __name__ == "__main__":
    main()
