"""Evening snapshot of tonight's SERVED forecast, for the daily answer-check loop.

Runs ~18:10 JST (before the 19:00 night starts), so it captures the pure
forward-looking forecast with no tonight-anchoring. The curve is saved to Supabase
Storage and scored against the realized counts next morning by score_forecasts.py.
This measures the LIVE forecast error — distinct from the training holdout MAE in
metadata.json / the accuracy card — and is exactly the gap that hid the
weather/skew bugs. See plan/FORECAST_ACCURACY.md.

Storage layout (reuses the existing model bucket, no new infra):
    <FORECAST_MODEL_BUCKET>/accuracy/snapshots/<YYYYMMDD>.json   (night of YYYYMMDD, JST)

Stdlib only. Requires SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY; BACKEND_URL optional.
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
DEFAULT_BACKEND = "https://riental-lounge-monitor.onrender.com"


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


def _oriental_slugs() -> list[str]:
    path = REPO_ROOT / "frontend" / "src" / "data" / "stores.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return [s["slug"] for s in data if s.get("brand", "oriental") == "oriental" and s.get("slug")]


def _get_json(url: str, retries: int = 3):
    last = ""
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode())
        except Exception as exc:  # noqa: BLE001
            last = str(exc)[:160]
            if attempt < retries:
                time.sleep(3 * attempt)
    print(f"[snapshot][warn] GET failed: {url} :: {last}")
    return None


def _storage_put(bucket: str, path: str, payload: bytes, url: str, key: str) -> None:
    endpoint = f"{url}/storage/v1/object/{bucket}/{path}"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "x-upsert": "true",
        "Content-Type": "application/json",
    }
    req = urllib.request.Request(endpoint, data=payload, method="POST", headers=headers)
    urllib.request.urlopen(req, timeout=30)


def main() -> int:
    _load_env()
    backend = (os.environ.get("BACKEND_URL") or DEFAULT_BACKEND).rstrip("/")
    supabase_url = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_SERVICE_KEY") or ""
    bucket = (os.environ.get("FORECAST_MODEL_BUCKET") or "ml-models").strip()
    if not supabase_url or not key:
        raise SystemExit("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")

    slugs = _oriental_slugs()
    night_date = datetime.now(JST).strftime("%Y%m%d")

    by_slug: dict[str, list] = {}
    for i in range(0, len(slugs), 40):  # forecast_today_multi accepts up to 40 stores
        chunk = slugs[i : i + 40]
        url = f"{backend}/api/forecast_today_multi?stores=" + urllib.parse.quote(",".join(chunk))
        data = _get_json(url)
        for slug, v in ((data or {}).get("by_slug") or {}).items():
            if isinstance(v, dict) and v.get("ok") and isinstance(v.get("data"), list):
                by_slug[slug] = [
                    {
                        "ts": p.get("ts"),
                        "total_pred": p.get("total_pred"),
                        "men_pred": p.get("men_pred"),
                        "women_pred": p.get("women_pred"),
                    }
                    for p in v["data"]
                    if isinstance(p, dict) and p.get("ts")
                ]

    payload = {
        "night_date": night_date,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "backend": backend,
        "stores": len(by_slug),
        "by_slug": by_slug,
    }
    path = f"accuracy/snapshots/{night_date}.json"
    _storage_put(bucket, path, json.dumps(payload, ensure_ascii=False).encode("utf-8"), supabase_url, key)
    print(f"[snapshot] saved {len(by_slug)}/{len(slugs)} stores -> {bucket}/{path}")
    if not by_slug:
        raise SystemExit("no forecasts captured (backend down or all stores empty)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
