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


def _slot_means(rows: list[dict]) -> dict[str, float]:
    """Average actual total per 15-min JST slot (multiple 5-min rows collapse into one)."""
    by_slot: dict[str, list[float]] = {}
    for r in rows:
        dt = _parse_iso(r.get("ts", ""))
        tot = _actual_total(r)
        if dt is None or tot is None:
            continue
        by_slot.setdefault(_slot_key(dt), []).append(tot)
    return {k: sum(v) / len(v) for k, v in by_slot.items()}


def _alert(message: str) -> None:
    """Post to OPS_NOTIFY_WEBHOOK_URL (Slack/Discord); no-op if unset. This is the
    'Act' in the answer-check PDCA loop: when the live forecast degrades or stops
    beating the naive baseline in production, ping a human to investigate/retrain."""
    url = (os.environ.get("OPS_NOTIFY_WEBHOOK_URL") or "").strip()
    if not url:
        print("[score][alert] (OPS_NOTIFY_WEBHOOK_URL unset) " + message)
        return
    try:
        req = urllib.request.Request(url, data=json.dumps({"text": message}).encode("utf-8"),
                                     method="POST", headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=15)
        print("[score][alert] sent: " + message)
    except Exception as exc:  # noqa: BLE001
        print(f"[score][alert] failed: {str(exc)[:150]}")


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

    # 7-days-earlier window for the LIVE seasonal-naive baseline ("same slot last week")
    start_prev_iso = (start - timedelta(days=7)).astimezone(timezone.utc).isoformat()
    end_prev_iso = (end - timedelta(days=7)).astimezone(timezone.utc).isoformat()

    per_store: dict[str, dict] = {}
    for slug, preds in by_slug.items():
        if not isinstance(preds, list) or not preds:
            continue
        # 相席屋は slug == store_id ("ay_*")。オリエンタルは短縮 slug なので "ol_" を付与。
        store_id = slug if slug.startswith("ay_") else f"ol_{slug}"
        slot_now = _slot_means(_fetch_actuals(supabase_url, key, store_id, start_iso, end_iso))
        slot_prev = _slot_means(_fetch_actuals(supabase_url, key, store_id, start_prev_iso, end_prev_iso))

        ml_err: list[float] = []
        base_err: list[float] = []
        for p in preds:
            dt = _parse_iso(p.get("ts", ""))
            if dt is None:
                continue
            actual = slot_now.get(_slot_key(dt))
            if actual is None:
                continue
            try:
                pred_total = float(p.get("total_pred") or 0.0)
            except (TypeError, ValueError):
                continue
            ml_err.append(abs(pred_total - actual))
            naive = slot_prev.get(_slot_key(dt - timedelta(days=7)))  # same clock slot, last week
            if naive is not None:
                base_err.append(abs(naive - actual))
        if ml_err:
            entry = {"live_mae": round(sum(ml_err) / len(ml_err), 2), "matched_slots": len(ml_err)}
            if base_err:
                b = sum(base_err) / len(base_err)
                entry["live_baseline_mae"] = round(b, 2)
                if b > 0:
                    # >0 means ML beats "same slot last week" in production; <=0 means it does not
                    entry["ml_vs_baseline_live_pct"] = round((b - entry["live_mae"]) / b * 100.0, 1)
            per_store[slug] = entry

    maes = [v["live_mae"] for v in per_store.values()]
    overall = round(sum(maes) / len(maes), 2) if maes else None
    base_maes = [v["live_baseline_mae"] for v in per_store.values() if "live_baseline_mae" in v]
    overall_baseline = round(sum(base_maes) / len(base_maes), 2) if base_maes else None
    result = {
        "night_date": night_date,
        "scored_at_utc": datetime.now(timezone.utc).isoformat(),
        "overall_live_mae": overall,
        "overall_baseline_mae": overall_baseline,
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
        [{"night_date": night_date, "overall_live_mae": overall,
          "overall_baseline_mae": overall_baseline, "stores_scored": len(per_store)}]
        + [n for n in summary["nights"] if n.get("night_date") != night_date]
    )[:SUMMARY_KEEP]
    summary["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
    _storage_put(bucket, "accuracy/scores/summary.json", json.dumps(summary, ensure_ascii=False).encode("utf-8"), supabase_url, key)

    # --- Act (close the PDCA loop): alert on production degradation ---
    alerts: list[str] = []
    if overall is not None and overall_baseline is not None and overall > overall_baseline:
        alerts.append(f"ML is NOT beating the naive baseline in production (live MAE {overall} vs naive {overall_baseline}).")
    recent = [n.get("overall_live_mae") for n in summary["nights"][1:8]
              if isinstance(n.get("overall_live_mae"), (int, float))]
    if overall is not None and recent:
        med = sorted(recent)[len(recent) // 2]
        if med > 0 and overall > med * 1.5:
            alerts.append(f"Live forecast error spiked: tonight {overall} vs recent median {round(med, 2)} (>1.5x).")
    if alerts:
        worst = sorted(per_store.items(), key=lambda kv: kv[1]["live_mae"], reverse=True)[:5]
        worst_str = ", ".join(f"{s}={v['live_mae']}" for s, v in worst)
        _alert(f"[MEGRIBI forecast accuracy] night {night_date}: " + " ".join(alerts) + f" Worst stores: {worst_str}")

    print(f"[score] night={night_date} overall_live_mae={overall} baseline={overall_baseline} stores_scored={len(per_store)}")
    for slug in sorted(per_store, key=lambda s: per_store[s]["live_mae"], reverse=True):
        v = per_store[slug]
        print(f"  {slug:<16} live_mae={v['live_mae']:>6}  slots={v['matched_slots']}")
    if not per_store:
        print("[score] no stores could be scored (no overlapping actual slots).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
