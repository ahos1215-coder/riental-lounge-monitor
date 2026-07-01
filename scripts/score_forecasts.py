"""Daily answer-check: score last night's snapshotted forecast against the actual
19:00–05:00 counts, per store.

Runs ~06:10 JST (after the night ends at 05:00). For each store it aligns the
snapshot's predicted curve with the realized `logs` totals on the same 15-minute
slots and computes the LIVE forecast MAE — the real-world error users experienced,
distinct from the training holdout MAE. Results are written per-night and appended
to a rolling summary in Supabase Storage so error can be tracked over time (and the
impact of changes like the weather fix can be seen as a real-world number).
See plan/FORECAST_ACCURACY.md.

Storage layout (reuses the existing model bucket):
    <bucket>/accuracy/snapshots/<YYYYMMDD>.json  (written by snapshot_forecasts.py)
    <bucket>/accuracy/scores/<YYYYMMDD>.json
    <bucket>/accuracy/scores/summary.json        (rolling, newest first)

Stdlib only. Requires SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
JST = timezone(timedelta(hours=9))
SLOT_MIN = 15
SUMMARY_KEEP = 60


def _load_env() -> None:
    for name in (".env", ".env.local"):
        p = REPO_ROOT / name
        if not p.is_file():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _parse_iso(s: str) -> datetime | None:
    if not isinstance(s, str) or not s.strip():
        return None
    t = s.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _slot_key(dt: datetime) -> str:
    """Floor a datetime to the JST 15-minute slot; stable string key."""
    j = dt.astimezone(JST)
    j = j.replace(minute=(j.minute // SLOT_MIN) * SLOT_MIN, second=0, microsecond=0)
    return j.strftime("%Y-%m-%dT%H:%M")


def _storage_get(bucket: str, path: str, url: str, key: str) -> bytes | None:
    endpoint = f"{url}/storage/v1/object/{bucket}/{path}"
    req = urllib.request.Request(endpoint, headers={"apikey": key, "Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def _storage_put(bucket: str, path: str, payload: bytes, url: str, key: str) -> None:
    endpoint = f"{url}/storage/v1/object/{bucket}/{path}"
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "x-upsert": "true", "Content-Type": "application/json"}
    req = urllib.request.Request(endpoint, data=payload, method="POST", headers=headers)
    urllib.request.urlopen(req, timeout=30)


def _fetch_actuals(url: str, key: str, store_id: str, start_iso: str, end_iso: str) -> list[dict]:
    endpoint = f"{url}/rest/v1/logs"
    params = [
        ("select", "ts,total,men,women"),
        ("store_id", f"eq.{store_id}"),
        ("ts", f"gte.{start_iso}"),
        ("ts", f"lte.{end_iso}"),
        ("order", "ts.asc"),
        ("limit", "5000"),
    ]
    full = endpoint + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full, headers={"apikey": key, "Authorization": f"Bearer {key}", "Accept": "application/json"})
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read().decode())
                return [r for r in payload if isinstance(r, dict)] if isinstance(payload, list) else []
        except Exception:  # noqa: BLE001
            if attempt < 3:
                time.sleep(2 * attempt)
    return []


def _actual_total(row: dict) -> float | None:
    for k in ("total",):
        v = row.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    men, women = row.get("men"), row.get("women")
    try:
        if men is not None and women is not None:
            return float(men) + float(women)
    except (TypeError, ValueError):
        pass
    return None


def main() -> int:
    _load_env()
    supabase_url = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_SERVICE_KEY") or ""
    bucket = (os.environ.get("FORECAST_MODEL_BUCKET") or "ml-models").strip()
    if not supabase_url or not key:
        raise SystemExit("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")

    # The night that just ended = yesterday (JST), since we run ~06:10 the next morning.
    night_date = (datetime.now(JST) - timedelta(days=1)).strftime("%Y%m%d")
    snap_raw = _storage_get(bucket, f"accuracy/snapshots/{night_date}.json", supabase_url, key)
    if snap_raw is None:
        print(f"[score] no snapshot for {night_date} — nothing to score (snapshot job may not have run).")
        return 0
    snapshot = json.loads(snap_raw.decode())
    by_slug = snapshot.get("by_slug") or {}

    base = datetime.strptime(night_date, "%Y%m%d").replace(tzinfo=JST)
    start = base.replace(hour=19, minute=0, second=0, microsecond=0)
    end = (start + timedelta(days=1)).replace(hour=5, minute=0, second=0, microsecond=0)
    start_iso = start.astimezone(timezone.utc).isoformat()
    end_iso = end.astimezone(timezone.utc).isoformat()

    per_store: dict[str, dict] = {}
    for slug, preds in by_slug.items():
        if not isinstance(preds, list) or not preds:
            continue
        store_id = f"ol_{slug}"
        rows = _fetch_actuals(supabase_url, key, store_id, start_iso, end_iso)
        actual_by_slot: dict[str, list[float]] = {}
        for r in rows:
            dt = _parse_iso(r.get("ts", ""))
            tot = _actual_total(r)
            if dt is None or tot is None:
                continue
            actual_by_slot.setdefault(_slot_key(dt), []).append(tot)
        slot_mean = {k: sum(v) / len(v) for k, v in actual_by_slot.items()}

        errors: list[float] = []
        for p in preds:
            dt = _parse_iso(p.get("ts", ""))
            if dt is None:
                continue
            actual = slot_mean.get(_slot_key(dt))
            if actual is None:
                continue
            try:
                pred_total = float(p.get("total_pred") or 0.0)
            except (TypeError, ValueError):
                continue
            errors.append(abs(pred_total - actual))
        if errors:
            per_store[slug] = {"live_mae": round(sum(errors) / len(errors), 2), "matched_slots": len(errors)}

    maes = [v["live_mae"] for v in per_store.values()]
    overall = round(sum(maes) / len(maes), 2) if maes else None
    result = {
        "night_date": night_date,
        "scored_at_utc": datetime.now(timezone.utc).isoformat(),
        "overall_live_mae": overall,
        "stores_scored": len(per_store),
        "per_store": per_store,
    }
    _storage_put(bucket, f"accuracy/scores/{night_date}.json", json.dumps(result, ensure_ascii=False).encode("utf-8"), supabase_url, key)

    # rolling summary (newest first, capped)
    summary = {"nights": []}
    existing = _storage_get(bucket, "accuracy/scores/summary.json", supabase_url, key)
    if existing is not None:
        try:
            loaded = json.loads(existing.decode())
            if isinstance(loaded, dict) and isinstance(loaded.get("nights"), list):
                summary = loaded
        except Exception:  # noqa: BLE001
            pass
    summary["nights"] = (
        [{"night_date": night_date, "overall_live_mae": overall, "stores_scored": len(per_store)}]
        + [n for n in summary["nights"] if n.get("night_date") != night_date]
    )[:SUMMARY_KEEP]
    summary["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
    _storage_put(bucket, "accuracy/scores/summary.json", json.dumps(summary, ensure_ascii=False).encode("utf-8"), supabase_url, key)

    print(f"[score] night={night_date} overall_live_mae={overall} stores_scored={len(per_store)}")
    for slug in sorted(per_store, key=lambda s: per_store[s]["live_mae"], reverse=True):
        v = per_store[slug]
        print(f"  {slug:<16} live_mae={v['live_mae']:>6}  slots={v['matched_slots']}")
    if not per_store:
        print("[score] no stores could be scored (no overlapping actual slots).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
