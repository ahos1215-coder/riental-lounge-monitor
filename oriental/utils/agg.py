from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional

import pandas as pd


@dataclass
class NightWindow:
    start_h: int = 19  # 19:00
    end_h: int = 5     # 05:00 （翌日）

    def mask(self, ts: pd.Series) -> pd.Series:
        h = ts.dt.hour
        return (h >= self.start_h) | (h < self.end_h)


def _as_dataframe(records: Iterable[dict], tz: str) -> pd.DataFrame:
    df = pd.DataFrame(records)
    if df.empty:
        return df
    # ts をタイムゾーン付きに統一
    df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce").dt.tz_convert(tz)
    df = df.dropna(subset=["ts"]).sort_values("ts")
    # 数値列（men, women, total）を確実に数値化
    for c in ("men", "women", "total"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    # total が無い/欠損なら men+women で補完
    if "total" not in df.columns:
        df["total"] = df.get("men", 0).fillna(0) + df.get("women", 0).fillna(0)
    else:
        df["total"] = df["total"].fillna(0)
        if "men" in df.columns and "women" in df.columns:
            df["total"] = df["total"].where(df["total"].notna(), df["men"].fillna(0) + df["women"].fillna(0))
    # 欠損は0で安全側に
    for c in ("men", "women", "total"):
        if c in df.columns:
            df[c] = df[c].fillna(0)
    return df


def aggregate_10m(
    records: Iterable[dict],
    *,
    tz: str = "Asia/Tokyo",
    start_h: int = 19,
    end_h: int = 5,
    store_id: Optional[str] = None,
) -> List[dict]:
    """
    任意粒度の履歴（5分/15分など）を 10分平均へ集計。
    - 対象時間帯は「夜窓」(既定 19:00–05:00) のみ
    - men / women / total は平均（スナップショットの平滑化が目的）
    - 返却の ts は 10分境界（:00, :10, :20, ...）のタイムスタンプ
    """
    df = _as_dataframe(records, tz)
    if df.empty:
        return []

    # 店舗で絞る（列名 store or store_id を許容）
    if store_id:
        sid_col = "store" if "store" in df.columns else ("store_id" if "store_id" in df.columns else None)
        if sid_col:
            df = df[df[sid_col] == store_id]

    if df.empty:
        return []

    # 夜窓フィルタ
    win = NightWindow(start_h=start_h, end_h=end_h)
    df = df[win.mask(df["ts"])]
    if df.empty:
        return []

    # 10分で平均化
    df = df.set_index("ts")
    g = df.resample("10T").mean(numeric_only=True)

    # total を再計算（安全側）
    if {"men", "women"}.issubset(g.columns):
        g["total"] = (g["men"].clip(lower=0) + g["women"].clip(lower=0)).fillna(0)
    else:
        g["total"] = g["total"].clip(lower=0).fillna(0)

    g = g[["men", "women", "total"]].fillna(0)

    # 出力：ISO文字列（TZ付き）
    out = [
        {
            "ts": ts.isoformat(),
            "men": float(row.get("men", 0.0)),
            "women": float(row.get("women", 0.0)),
            "total": float(row.get("total", 0.0)),
        }
        for ts, row in g.iterrows()
    ]
    return out
