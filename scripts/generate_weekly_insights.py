from __future__ import annotations

import argparse
import importlib.util
import inspect
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
MEGRIBI_SCORE_PATH = REPO_ROOT / "oriental" / "ml" / "megribi_score.py"

if not MEGRIBI_SCORE_PATH.exists():
    raise SystemExit(f"megribi_score not found: {MEGRIBI_SCORE_PATH}")

spec = importlib.util.spec_from_file_location("megribi_score", MEGRIBI_SCORE_PATH)
if spec is None or spec.loader is None:
    raise SystemExit("failed to load megribi_score module")

megribi_score_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(megribi_score_module)

find_good_windows = megribi_score_module.find_good_windows


DEFAULT_BASE_URL = "https://www.meguribi.jp"
DEFAULT_LIMIT = 5000
DEFAULT_SCORE_THRESHOLD = 0.80
DEFAULT_MIN_DURATION_MINUTES = 120
DEFAULT_IDEAL = 0.7
DEFAULT_GENDER_WEIGHT = 1.5


def _pick_value(row: dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        if key in row:
            return row[key]
    return None


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_timestamp(row: dict[str, Any]) -> datetime | None:
    raw = _pick_value(row, ("timestamp", "ts", "t", "observed_at", "observedAt", "created_at", "createdAt"))
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        value = float(raw)
        if value > 1e12:
            value /= 1000.0
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed
    return None


def _percentile(values: list[float], percent: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (len(sorted_values) - 1) * (percent / 100.0)
    lower = int(rank)
    upper = min(lower + 1, len(sorted_values) - 1)
    if lower == upper:
        return sorted_values[lower]
    weight = rank - lower
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * weight


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _load_rows(base_url: str, store: str, limit: int) -> list[dict[str, Any]]:
    query = urlencode({"store": store, "limit": str(limit)})
    url = f"{base_url.rstrip('/')}/api/range?{query}"
    req = Request(url, headers={"accept": "application/json"})
    with urlopen(req, timeout=20) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        rows = payload.get("rows")
        if isinstance(rows, list):
            return rows
    return []


def _collect_totals(rows: list[dict[str, Any]]) -> list[float]:
    totals: list[float] = []
    for row in rows:
        total = _to_float(_pick_value(row, ("total", "sum")))
        if total is None:
            men = _to_float(_pick_value(row, ("men", "male", "m")))
            women = _to_float(_pick_value(row, ("women", "female", "f")))
            if men is None or women is None:
                continue
            total = men + women
        if total is None:
            continue
        totals.append(total)
    return totals


def _build_points(rows: list[dict[str, Any]], baseline: float) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for row in rows:
        dt = _parse_timestamp(row)
        if dt is None:
            continue
        men = _to_float(_pick_value(row, ("men", "male", "m")))
        women = _to_float(_pick_value(row, ("women", "female", "f")))
        if men is None or women is None:
            continue
        denom = men + women
        if denom <= 0:
            continue
        female_ratio = women / denom
        total = _to_float(_pick_value(row, ("total", "sum")))
        if total is None:
            total = denom
        if baseline > 0:
            occupancy_rate = min(1.0, total / baseline)
        else:
            occupancy_rate = 0.0
        points.append(
            {
                "timestamp": dt,
                "female_ratio": female_ratio,
                "occupancy_rate": occupancy_rate,
                "stability": 1.0,
            }
        )
    return points


def _serialize_windows(windows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for w in windows:
        out.append(
            {
                "start": _iso(w.get("start")),
                "end": _iso(w.get("end")),
                "duration_minutes": w.get("duration_minutes"),
                "avg_score": w.get("avg_score"),
            }
        )
    return out


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _parse_store_list(value: str | None) -> list[str]:
    if not value:
        return []
    raw = value.replace(",", " ").split()
    return [item.strip() for item in raw if item.strip()]


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _call_find_good_windows(points: list[dict[str, Any]], **kwargs: Any) -> list[dict[str, Any]]:
    sig = inspect.signature(find_good_windows)
    accepts_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
    if accepts_var_kw:
        return find_good_windows(points, **kwargs)
    filtered = {key: value for key, value in kwargs.items() if key in sig.parameters}
    return find_good_windows(points, **filtered)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stores", help="comma/space separated store slugs")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--threshold", type=float)
    parser.add_argument("--min-duration-minutes", type=int)
    parser.add_argument("--ideal", type=float)
    parser.add_argument("--gender-weight", type=float)
    args = parser.parse_args()

    stores_value = args.stores or os.environ.get("INSIGHTS_STORES")
    stores = _parse_store_list(stores_value)
    if not stores:
        raise SystemExit("stores are required. Use --stores or INSIGHTS_STORES.")

    threshold = args.threshold if args.threshold is not None else _env_float("INSIGHTS_THRESHOLD", DEFAULT_SCORE_THRESHOLD)
    min_duration_minutes = (
        args.min_duration_minutes
        if args.min_duration_minutes is not None
        else _env_int("INSIGHTS_MIN_DURATION_MINUTES", DEFAULT_MIN_DURATION_MINUTES)
    )
    ideal = args.ideal if args.ideal is not None else _env_float("INSIGHTS_IDEAL", DEFAULT_IDEAL)
    gender_weight = (
        args.gender_weight
        if args.gender_weight is not None
        else _env_float("INSIGHTS_GENDER_WEIGHT", DEFAULT_GENDER_WEIGHT)
    )

    base_url = (
        os.environ.get("MEGRIBI_BASE_URL")
        or os.environ.get("NEXT_PUBLIC_BASE_URL")
        or DEFAULT_BASE_URL
    )

    base_dir = REPO_ROOT / "frontend" / "content" / "insights" / "weekly"
    _ensure_dir(base_dir)

    index_path = base_dir / "index.json"
    index_payload: dict[str, Any] = {}
    if index_path.exists():
        try:
            index_payload = json.loads(index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            index_payload = {}

    stores_index = index_payload.get("stores")
    if not isinstance(stores_index, dict):
        stores_index = {}

    now = datetime.now(timezone.utc)
    date_label = now.date().isoformat()
    generated_at = _iso(now)

    for store in stores:
        rows = _load_rows(base_url, store, args.limit)
        timestamps = [ts for ts in (_parse_timestamp(r) for r in rows) if ts is not None]
        period_start = min(timestamps) if timestamps else None
        period_end = max(timestamps) if timestamps else None

        totals = _collect_totals(rows)
        baseline = _percentile(totals, 95.0) if totals else 0.0
        baseline = baseline if baseline > 0 else 0.0

        points = _build_points(rows, baseline)
        windows = _call_find_good_windows(
            points,
            score_threshold=threshold,
            min_duration_minutes=min_duration_minutes,
            ideal=ideal,
            gender_weight=gender_weight,
        )
        serialized_windows = _serialize_windows(windows)
        top_windows = sorted(
            serialized_windows,
            key=lambda w: w.get("avg_score") or 0,
            reverse=True,
        )[:3]

        payload = {
            "analysis_id": f"weekly:{store}:{date_label}",
            "type": "weekly",
            "store": store,
            "generated_at": generated_at,
            "period": {"start": _iso(period_start), "end": _iso(period_end)},
            "params": {
                "threshold": threshold,
                "min_duration_minutes": min_duration_minutes,
                "ideal": ideal,
                "gender_weight": gender_weight,
                "occupancy_baseline": baseline,
            },
            "metrics": {
                "points_used": len(points),
                "baseline_p95_total": baseline,
                "reliability_score": min(1.0, len(points) / 200.0),
            },
            "windows": serialized_windows,
            "top_windows": top_windows,
        }

        store_dir = base_dir / store
        _ensure_dir(store_dir)
        out_path = store_dir / f"{date_label}.json"
        with out_path.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=True, indent=2)
            handle.write("\n")

        stores_index[store] = {"latest_file": out_path.name, "generated_at": generated_at}

    index_payload["generated_at"] = generated_at
    index_payload["stores"] = stores_index
    with index_path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(index_payload, handle, ensure_ascii=True, indent=2)
        handle.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
