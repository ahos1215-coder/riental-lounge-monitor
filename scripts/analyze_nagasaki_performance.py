from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from oriental.ml.preprocess import FEATURE_COLUMNS

WATCH_FEATURES = {
    "feat_payday_night_peak",
    "feat_rain_night_exit",
    "feat_pre_holiday_surge",
    "days_from_25th",
    "minutes_to_midnight",
    "precip_mm",
    "is_rainy",
    "is_pre_holiday",
    "is_holiday",
}


def _latest_artifact_json(artifacts_dir: Path, *, preferred_date: str = "20260324") -> Path:
    files = [p for p in artifacts_dir.glob("*.json") if p.is_file()]
    if not files:
        raise SystemExit(f"artifacts json not found: {artifacts_dir}")
    preferred = [p for p in files if preferred_date in p.stem]
    pool = preferred if preferred else files
    return max(pool, key=lambda p: p.stat().st_mtime)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"failed to parse json: {path} ({exc})")
    if not isinstance(payload, dict):
        raise SystemExit(f"json root must be object: {path}")
    return payload


def _extract_metrics(payload: dict[str, Any]) -> tuple[float | None, float | None]:
    overall_mae = None
    segment_mae = None

    # Pattern 1: training-style metrics in top-level store logs
    overall = payload.get("overall")
    if isinstance(overall, dict):
        overall_mae = _as_float(overall.get("total_mae")) or _as_float(overall.get("mae"))
    segment = payload.get("weekend_night_segment")
    if isinstance(segment, dict):
        segment_mae = _as_float(segment.get("total_mae")) or _as_float(segment.get("mae"))

    # Pattern 2: experiment reports
    if overall_mae is None or segment_mae is None:
        experiments = payload.get("experiments")
        if isinstance(experiments, dict):
            # Prefer 60-min if exists, else latest key
            key = "60" if "60" in experiments else next(iter(experiments.keys()), None)
            if key and isinstance(experiments.get(key), dict):
                exp = experiments[key]
                metrics = exp.get("metrics")
                if isinstance(metrics, dict):
                    overall_mae = overall_mae or _as_float(metrics.get("mae")) or _as_float(metrics.get("total_mae"))
                    segment_mae = segment_mae or _as_float(metrics.get("h21_25_mae"))

    # Pattern 3: ablation segment
    if overall_mae is None or segment_mae is None:
        ablation = payload.get("ablation")
        if isinstance(ablation, dict):
            full = ablation.get("full")
            if isinstance(full, dict):
                m = full.get("metrics")
                if isinstance(m, dict):
                    overall_mae = overall_mae or _as_float(m.get("mae"))
        seg = payload.get("segment_peak_fri_sat_preholiday_20_25")
        if isinstance(seg, dict):
            m = seg.get("metrics")
            if isinstance(m, dict):
                segment_mae = segment_mae or _as_float(m.get("mae"))

    return overall_mae, segment_mae


def _extract_gain(payload: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}

    direct = payload.get("gain_watch_features")
    if isinstance(direct, dict):
        for k, v in direct.items():
            fv = _as_float(v)
            if fv is not None:
                out[k] = fv

    experiments = payload.get("experiments")
    if isinstance(experiments, dict):
        key = "60" if "60" in experiments else next(iter(experiments.keys()), None)
        if key and isinstance(experiments.get(key), dict):
            gains = experiments[key].get("gain_watch_features")
            if isinstance(gains, dict):
                for k, v in gains.items():
                    fv = _as_float(v)
                    if fv is not None:
                        out[k] = fv

    ablation = payload.get("ablation")
    if isinstance(ablation, dict):
        full = ablation.get("full")
        if isinstance(full, dict):
            gains = full.get("watch_gain")
            if isinstance(gains, dict):
                for k, v in gains.items():
                    fv = _as_float(v)
                    if fv is not None:
                        out[k] = fv

    return out


def _as_float(v: Any) -> float | None:
    try:
        return float(v)
    except Exception:  # noqa: BLE001
        return None


def main() -> int:
    artifacts_dir = REPO_ROOT / "artifacts"
    latest = _latest_artifact_json(artifacts_dir)
    payload = _read_json(latest)

    store_id = str(payload.get("store_id") or "unknown")
    if store_id != "ol_nagasaki":
        print(f"[warn] latest artifact store_id is not ol_nagasaki: {store_id}")

    overall_mae, segment_mae = _extract_metrics(payload)
    gains = _extract_gain(payload)
    all_feature_gains = {name: float(gains.get(name, 0.0)) for name in FEATURE_COLUMNS}
    top_n = 20
    ranked = sorted(all_feature_gains.items(), key=lambda x: x[1], reverse=True)[:top_n]
    watch_positive = {k: v for k, v in gains.items() if k in WATCH_FEATURES and v > 0.0}

    print(f"[analyze] artifact: {latest.name}")
    print(f"[analyze] store_id: {store_id}")
    print(f"[analyze] overall_mae: {overall_mae if overall_mae is not None else 'n/a'}")
    print(f"[analyze] weekend_night_segment_mae: {segment_mae if segment_mae is not None else 'n/a'}")
    print(f"[analyze] feature gain ranking top{top_n}:")
    if not ranked:
        print("  (none)")
    else:
        name_w = max(len(name) for name, _ in ranked)
        for i, (name, gain) in enumerate(ranked, start=1):
            print(f"  {i:>2}. {name:<{name_w}}  {gain:>10.6f}")

    print("[analyze] positive watch-feature gains:")
    if not watch_positive:
        print("  (none)")
    else:
        for name, gain in sorted(watch_positive.items(), key=lambda x: x[1], reverse=True):
            print(f"  - {name}: {gain:.6f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

