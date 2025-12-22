from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Iterable, List, Dict, Any, Optional, Tuple


def clamp01(x: Any) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(v) or math.isinf(v):
        return 0.0
    if v < 0.0:
        return 0.0
    if v > 1.0:
        return 1.0
    return v


def _occupancy_score(occupancy_rate: Any, ideal: Any) -> float:
    occ = clamp01(occupancy_rate)
    ideal_v = clamp01(ideal)
    if ideal_v <= 0.0:
        return clamp01(1.0 - occ)
    if ideal_v >= 1.0:
        return clamp01(occ)
    if occ <= ideal_v:
        return clamp01(1.0 - (ideal_v - occ) / ideal_v)
    return clamp01(1.0 - (occ - ideal_v) / (1.0 - ideal_v))


def megribi_score(
    female_ratio: Any,
    occupancy_rate: Any,
    stability: Any = 1.0,
    ideal: float = 0.7,
    gender_weight: float = 1.5,
) -> float:
    occ_score = _occupancy_score(occupancy_rate, ideal)
    fr = clamp01(female_ratio)
    weight = max(0.0, float(gender_weight))
    female_score = clamp01(0.5 + (fr - 0.5) * weight)
    stability_score = clamp01(stability)
    return clamp01(occ_score * female_score * stability_score)


def _to_datetime(ts: Any) -> Optional[datetime]:
    if isinstance(ts, datetime):
        return ts
    if isinstance(ts, (int, float)) and math.isfinite(ts):
        value = float(ts)
        if value > 1e12:
            value /= 1000.0
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(ts, str):
        s = ts.strip()
        if not s:
            return None
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(s)
        except ValueError:
            return None
    return None


def _extract_point(point: Any) -> Optional[Tuple[datetime, Any, Any, Any]]:
    if isinstance(point, dict):
        ts = point.get("timestamp", point.get("ts"))
        female_ratio = point.get("female_ratio", point.get("femaleRatio"))
        occupancy_rate = point.get("occupancy_rate", point.get("occupancyRate"))
        stability = point.get("stability", 1.0)
    elif isinstance(point, (list, tuple)) and len(point) >= 3:
        ts = point[0]
        female_ratio = point[1]
        occupancy_rate = point[2]
        stability = point[3] if len(point) > 3 else 1.0
    else:
        return None

    dt = _to_datetime(ts)
    if dt is None:
        return None
    return dt, female_ratio, occupancy_rate, stability


def find_good_windows(
    points: Iterable[Any],
    score_threshold: float = 0.80,
    min_duration_minutes: int = 120,
) -> List[Dict[str, Any]]:
    scored: List[Tuple[datetime, float]] = []
    for point in points:
        parsed = _extract_point(point)
        if not parsed:
            continue
        dt, female_ratio, occupancy_rate, stability = parsed
        score = megribi_score(
            female_ratio=female_ratio,
            occupancy_rate=occupancy_rate,
            stability=stability,
        )
        scored.append((dt, score))

    scored.sort(key=lambda item: item[0])

    windows: List[Dict[str, Any]] = []
    segment: List[Tuple[datetime, float]] = []
    threshold = float(score_threshold)

    def flush_segment() -> None:
        if not segment:
            return
        start_dt = segment[0][0]
        end_dt = segment[-1][0]
        duration_minutes = (end_dt - start_dt).total_seconds() / 60.0
        if duration_minutes >= float(min_duration_minutes):
            avg_score = sum(s for _, s in segment) / len(segment)
            windows.append(
                {
                    "start": start_dt,
                    "end": end_dt,
                    "duration_minutes": duration_minutes,
                    "avg_score": avg_score,
                }
            )
        segment.clear()

    for dt, score in scored:
        if score >= threshold:
            segment.append((dt, score))
        else:
            flush_segment()

    flush_segment()
    return windows
