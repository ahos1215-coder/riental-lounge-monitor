"""CDN warming for https://www.meguribi.jp — local Task Scheduler runner.

Why this exists
----------------
`.github/workflows/warm-cdn.yml` (GitHub Actions `schedule:` every 10 min,
19:00-23:50 JST) was measured to actually fire only 5 of ~60 expected runs
over 2 nights (8.3%), with gaps of 1.5-3h — GitHub's cron scheduler silently
delays/drops runs under load. Warming was effectively dead, so real visitors
kept hitting cold APIs (1-9s) instead of the warm CDN path (10-30ms).

This script runs the same warming job from the owner's 24/7 Windows PC via
Task Scheduler instead — the same box that already runs the production
`MEGRIBI-daily-evening` / `MEGRIBI-daily-late` / `MEGRIBI-weekly` jobs (see
docs/LOCAL_LLM_SETUP.md and plan/CDN_WARMING_LOCAL.md). Task Scheduler's own
minute-repetition trigger does not suffer from GitHub Actions' scheduler
throttling, so this becomes the *primary* warmer; warm-cdn.yml stays wired up
unchanged as an opportunistic backup (it still helps on the rare pass where
GHA's cron actually fires on time).

URL shapes — CDN cache keys are exact (path + query string), so every URL
built here mirrors the real client code byte-for-byte. Sources (read, not
guessed):
  - frontend/src/app/hooks/storePreviewSnapshot.ts   (RANGE_LIMIT_BY_MODE,
    computeNightBaseDate/computeSelectedNightBaseDate/isNightCompleted,
    nightDateYYYYMMDD)
  - frontend/src/app/hooks/useStorePreviewData.ts     (range/forecast URL
    construction for the store detail page: today + yesterday tabs)
  - frontend/src/app/stores/stores-list-client.tsx    (list-page range_multi
    / forecast_today_multi / megribi_score csv construction, 12/page)
  - frontend/src/app/store/[id]/StorePageClient.tsx   (per-store "related
    stores" range_multi — nearest-4-by-haversine digestStores)
  - frontend/src/app/home-client.tsx                  (top page: bare
    megribi_score + /api/range for the fallback "last visited" store)
  - frontend/src/app/config/stores.ts                 (distanceKm haversine
    formula, STORES order == frontend/src/data/stores.json order)
  - frontend/src/lib/storeCardRangeSparkline.ts        (STORE_CARD_RANGE_LIMIT)

Rate-limit note (important, discovered while building this -- confirmed by an
actual 429 burst in the first live verification run): every one of these
Next.js API routes (frontend/src/app/api/*/route.ts) calls
`rateLimit(req, "<prefix>", N)` (frontend/src/lib/rateLimit/apiRateLimit.ts)
— an in-memory, per-(prefix, client-IP) sliding-window limiter with defaults
like 60/min for "range", 30/min for "range_multi"/"forecast_today"/
"forecast_snapshot", 20/min for "forecast_multi". This box's IP is the only
consumer of its own bucket, but with 43 stores the *volume* per prefix
(~87 "range" hits, ~47 "range_multi" hits per pass) exceeds those per-minute
budgets if clustered together. The first live run appended the 43 "related
stores" range_multi hits as one contiguous block at the end -- 13 of them
came back 429. Fix: `build_all_urls` interleaves each store's related-stores
hit right after that store's own request block, so same-prefix requests are
spread across the whole (multi-minute -- real backend latency dominates,
see DEFAULT_SLEEP_SECONDS) pass instead of bursted. The explicit sleep
between requests (WARM_SLEEP_SECONDS) is a secondary safety floor on top of
that, not the primary defense. Tolerated regardless: any individual failure
(including a stray 429) just counts against the run's fail ratio, it doesn't
abort the pass. See plan/CDN_WARMING_LOCAL.md for the full writeup.

Design constraints
------------------
- Standard library only (urllib/json/datetime/math) — no pip install step
  needed on the Task Scheduler box.
- Window guard: exits 0 immediately if current JST time is outside
  WARM_WINDOW_START..WARM_WINDOW_END (default 18:55-24:05, override via env)
  so a mistimed/duplicated Task Scheduler trigger is a safe no-op.
- Best-effort: per-URL failures (timeout, 5xx, 429, ...) don't abort the run;
  only >50% overall failure makes the process exit 1 (signals a real backend
  outage worth alerting on).
- Small daily-rotating log file under %TEMP% (or WARM_CDN_LOG_DIR) with one
  line per URL plus a pass summary.

Usage
-----
    python scripts/warm_cdn_local.py                  # normal run (--once is default/only mode)
    python scripts/warm_cdn_local.py --once
    WARM_WINDOW_START=00:00 WARM_WINDOW_END=23:59 python scripts/warm_cdn_local.py   # force-run for testing

Task Scheduler registration (run by the orchestrator, NOT by this script) —
mirrors the existing MEGRIBI-* tasks' conventions (docs/LOCAL_LLM_SETUP.md):

    $py = "C:\\Users\\ahos1\\AppData\\Local\\Programs\\Python\\Python314\\python.exe"
    $root = "C:\\Users\\Public\\共有データ系\\ORIENTAL\\ORIENTAL\\riental-lounge-monitor-main"

    schtasks /Create /TN "MEGRIBI-warm-cdn" /SC DAILY /ST 19:00 /RI 10 /DU 0005:00 /F `
      /TR "$py $root\\scripts\\warm_cdn_local.py"

    $s = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -AllowStartIfOnBatteries `
         -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
    Set-ScheduledTask -TaskName "MEGRIBI-warm-cdn" -Settings $s

/SC DAILY /ST 19:00 /RI 10 /DU 0005:00 = daily at 19:00, then repeat every 10
minutes for a 5-hour duration (last fire 23:50) — the Task Scheduler-native
equivalent of the GHA `cron: "*/10 10-14 * * *"` window. No admin//RU needed
(same as the other MEGRIBI-* tasks — interactive logon is fine).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
STORES_JSON_PATH = REPO_ROOT / "frontend" / "src" / "data" / "stores.json"

JST = timezone(timedelta(hours=9))
DEFAULT_BASE_URL = "https://www.meguribi.jp"

# frontend/src/lib/storeCardRangeSparkline.ts STORE_CARD_RANGE_LIMIT
STORE_CARD_RANGE_LIMIT = 48
# frontend/src/app/hooks/storePreviewSnapshot.ts RANGE_LIMIT_BY_MODE
RANGE_LIMIT_TODAY = 240
RANGE_LIMIT_YESTERDAY = 1200
# frontend/src/app/stores/stores-list-client.tsx STORES_PER_PAGE
STORES_PER_PAGE = 12
# frontend/src/app/store/[id]/StorePageClient.tsx digestStores: .slice(0, 4)
RELATED_STORE_COUNT = 4

# Default request pacing. See the "Rate-limit note" in the module docstring.
# The primary defense against self-inflicted 429s is `build_all_urls`
# interleaving same-prefix requests across the whole pass (rather than
# clustering them); this sleep is a secondary floor on top of that. Measured
# in a live pass against production: 229 URLs against the single-worker
# Render backend (several forecast endpoints doing real ML inference) take
# several minutes end-to-end regardless of this value, since real request
# latency dominates -- so this stays close to the originally-suggested
# 0.15-0.25s rather than being stretched further for rate-limit purposes.
DEFAULT_SLEEP_SECONDS = 0.2
DEFAULT_TIMEOUT_SECONDS = 20
DEFAULT_WINDOW_START = "18:55"
DEFAULT_WINDOW_END = "24:05"


# --------------------------------------------------------------------------
# Store data
# --------------------------------------------------------------------------


def load_stores(path: Path = STORES_JSON_PATH) -> list[dict]:
    """Load stores.json, preserving file order (== frontend STORES order,
    frontend/src/app/config/stores.ts `STORES = rawStores.map(...)`)."""
    with path.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    out = []
    for s in raw:
        slug = s.get("slug")
        if not slug:
            continue
        out.append({"slug": slug, "lat": s.get("lat"), "lon": s.get("lon")})
    return out


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Mirrors frontend/src/app/config/stores.ts `distanceKm` exactly (same
    formula, same units, same R=6371)."""
    r = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    s = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2
    )
    return 2 * r * math.asin(math.sqrt(s))


def nearest_related_slugs(stores: list[dict], slug: str, count: int = RELATED_STORE_COUNT) -> list[str]:
    """Mirrors StorePageClient.tsx `digestStores`: nearest `count` other
    stores by haversine distance, nearest first, ties broken by original
    stores.json order. All 43 stores.json entries carry lat/lon (verified),
    so the region-label fallback branch in distanceKm's caller never
    triggers here and is intentionally not replicated.
    """
    me = next((s for s in stores if s["slug"] == slug), None)
    if me is None or me.get("lat") is None or me.get("lon") is None:
        return []

    scored: list[tuple[float, int, str]] = []
    i = 0
    for s in stores:
        if s["slug"] == slug:
            continue
        if s.get("lat") is None or s.get("lon") is None:
            i += 1
            continue
        d = haversine_km(me["lat"], me["lon"], s["lat"], s["lon"])
        scored.append((d, i, s["slug"]))
        i += 1

    scored.sort(key=lambda t: (t[0], t[1]))
    return [slug for _, _, slug in scored[:count]]


# --------------------------------------------------------------------------
# Night-window date math — mirrors frontend/src/app/hooks/storePreviewSnapshot.ts
# --------------------------------------------------------------------------


def compute_night_base_date(now_jst: datetime) -> date:
    """Mirrors `computeNightBaseDate`: JST calendar date, rolled back one day
    before 19:00 (the still-relevant night is the one that started
    yesterday at 19:00 until this evening's night begins)."""
    d = now_jst.date()
    if now_jst.hour < 19:
        d = d - timedelta(days=1)
    return d


def night_window_end(base_date: date) -> datetime:
    """Mirrors `computeNightWindowFromBaseDate(baseDate).end`: base_date+1
    at 05:00 JST."""
    nxt = base_date + timedelta(days=1)
    return datetime(nxt.year, nxt.month, nxt.day, 5, 0, tzinfo=JST)


def is_night_completed(base_date: date, now_jst: datetime) -> bool:
    """Mirrors `isNightCompleted`."""
    return now_jst >= night_window_end(base_date)


def ymd(d: date) -> str:
    return d.isoformat()


def ymd_compact(d: date) -> str:
    """Mirrors `nightDateYYYYMMDD`: YYYYMMDD, no separators."""
    return d.strftime("%Y%m%d")


# --------------------------------------------------------------------------
# URL building (pure functions — unit tested against known-good literals in
# tests/test_warm_cdn_local.py)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class WarmUrl:
    url: str
    label: str
    prefix: str  # matches the Next.js rateLimit() bucket name for this route


def build_store_urls(base: str, stores: list[dict], now_jst: datetime) -> list[WarmUrl]:
    """Per-store URLs for the store detail page's "today" and "yesterday"
    tabs (useStorePreviewData.ts). 4 requests/store in the normal operating
    window (19:00-24:05 JST): range today, range yesterday, forecast for
    the in-progress night, and the snapshot for yesterday's completed
    night (the two forecast sources the "today"/"yesterday" tab toggle
    actually fetches).
    """
    base_date = compute_night_base_date(now_jst)
    tomorrow = base_date + timedelta(days=1)
    yesterday = base_date - timedelta(days=1)

    # In the script's normal 19:00-24:05 JST operating window this is always
    # False (tonight's night just started, isNightCompleted only flips true
    # after next-day 05:00). Computed properly (not assumed) so the tiny
    # 18:55-18:59 pre-19:00 guard-window sliver still resolves correctly —
    # see isNightCompleted's docstring in storePreviewSnapshot.ts.
    today_completed = is_night_completed(base_date, now_jst)

    out: list[WarmUrl] = []
    for s in stores:
        slug = s["slug"]
        out.append(
            WarmUrl(
                f"{base}/api/range?store={slug}&from={ymd(base_date)}&to={ymd(tomorrow)}&limit={RANGE_LIMIT_TODAY}",
                f"{slug}:range_today",
                "range",
            )
        )
        out.append(
            WarmUrl(
                f"{base}/api/range?store={slug}&from={ymd(yesterday)}&to={ymd(base_date)}&limit={RANGE_LIMIT_YESTERDAY}",
                f"{slug}:range_yesterday",
                "range",
            )
        )
        if today_completed:
            out.append(
                WarmUrl(
                    f"{base}/api/forecast_snapshot?store={slug}&date={ymd_compact(base_date)}",
                    f"{slug}:forecast_today_snapshot",
                    "forecast_snapshot",
                )
            )
        else:
            out.append(
                WarmUrl(
                    f"{base}/api/forecast_today?store={slug}",
                    f"{slug}:forecast_today",
                    "forecast_today",
                )
            )
        # The "yesterday" tab's night is always completed by the time this
        # script runs (18:55+ JST is always past yesterday+1day 05:00 JST).
        out.append(
            WarmUrl(
                f"{base}/api/forecast_snapshot?store={slug}&date={ymd_compact(yesterday)}",
                f"{slug}:forecast_yesterday_snapshot",
                "forecast_snapshot",
            )
        )
    return out


def build_list_page_urls(base: str, stores: list[dict]) -> list[WarmUrl]:
    """List page (/stores), default view (no filter/search): pages of
    STORES_PER_PAGE in stores.json order (stores-list-client.tsx)."""
    out: list[WarmUrl] = []
    page_count = math.ceil(len(stores) / STORES_PER_PAGE) if stores else 0
    for page in range(page_count):
        chunk = stores[page * STORES_PER_PAGE : (page + 1) * STORES_PER_PAGE]
        csv = ",".join(s["slug"] for s in chunk)
        page_no = page + 1
        out.append(
            WarmUrl(
                f"{base}/api/range_multi?stores={csv}&limit={STORE_CARD_RANGE_LIMIT}",
                f"list_page{page_no}:range_multi",
                "range_multi",
            )
        )
        out.append(
            WarmUrl(
                f"{base}/api/forecast_today_multi?stores={csv}",
                f"list_page{page_no}:forecast_today_multi",
                "forecast_multi",
            )
        )
        out.append(
            WarmUrl(
                f"{base}/api/megribi_score?stores={csv}",
                f"list_page{page_no}:megribi_score",
                "megribi_score",
            )
        )
    return out


def build_related_store_urls(base: str, stores: list[dict]) -> list[WarmUrl]:
    """Store detail page's "related stores" panel (StorePageClient.tsx
    digestStores): one range_multi per store, keyed to that store's own
    nearest-4-by-distance CSV (43 distinct combos, since the CSV order/
    membership depends on the current store)."""
    out: list[WarmUrl] = []
    for s in stores:
        slug = s["slug"]
        related = nearest_related_slugs(stores, slug)
        if not related:
            continue
        csv = ",".join(related)
        out.append(
            WarmUrl(
                f"{base}/api/range_multi?stores={csv}&limit={STORE_CARD_RANGE_LIMIT}",
                f"{slug}:related_range_multi",
                "range_multi",
            )
        )
    return out


def build_top_page_urls(base: str, stores: list[dict]) -> list[WarmUrl]:
    """Top page (home-client.tsx): bare megribi_score (all stores, no
    filter) + the "last visited store" range fetch, warmed for the
    fallback default store (DEFAULT_STORE = STORES[0].slug) since that's
    what a first-time visitor with no localStorage history gets."""
    out = [WarmUrl(f"{base}/api/megribi_score", "top:megribi_score", "megribi_score")]
    if stores:
        default_slug = stores[0]["slug"]
        out.append(
            WarmUrl(
                f"{base}/api/range?store={default_slug}&limit={STORE_CARD_RANGE_LIMIT}",
                "top:range_default_store",
                "range",
            )
        )
    return out


def build_all_urls(base: str, stores: list[dict], now_jst: datetime) -> list[WarmUrl]:
    """Assembles the full warm list. IMPORTANT ordering note (found via a
    live 429 burst in the first verification run of this script): the 43
    "related stores" range_multi hits (build_related_store_urls) must NOT
    be appended as one contiguous block -- that clusters 43 same-prefix
    ("range_multi") requests together, blowing past the route's 30/min
    rate limit (frontend/src/lib/rateLimit/apiRateLimit.ts) in well under a
    minute and causing self-inflicted 429s (confirmed: 13/43 failed with
    429 when this was a trailing block). Instead each store's related-stores
    hit is interleaved right after that same store's own 4-request block, so
    the 47 total range_multi hits (4 list-page + 43 related) are spread
    across the whole pass (which runs several minutes end-to-end against a
    single-worker backend) rather than bursted.
    """
    urls: list[WarmUrl] = []
    urls.extend(build_top_page_urls(base, stores))
    urls.extend(build_list_page_urls(base, stores))

    store_urls = build_store_urls(base, stores, now_jst)
    related_by_slug = {u.label.split(":", 1)[0]: u for u in build_related_store_urls(base, stores)}
    per_store = len(store_urls) // len(stores) if stores else 0
    for idx, s in enumerate(stores):
        urls.extend(store_urls[idx * per_store : (idx + 1) * per_store])
        rel = related_by_slug.get(s["slug"])
        if rel is not None:
            urls.append(rel)
    return urls


# --------------------------------------------------------------------------
# Window guard
# --------------------------------------------------------------------------


def parse_hhmm_to_minutes(value: str) -> int:
    """Parses "HH:MM" into minutes-since-midnight. Hour may be >=24 to
    express a window that crosses midnight (e.g. "24:05" == 00:05 the next
    day) — see `in_warm_window`."""
    h_str, m_str = value.strip().split(":")
    return int(h_str) * 60 + int(m_str)


def in_warm_window(now_jst: datetime, start: str, end: str) -> bool:
    start_min = parse_hhmm_to_minutes(start)
    end_min = parse_hhmm_to_minutes(end)
    now_min = now_jst.hour * 60 + now_jst.minute
    if end_min > 24 * 60:
        # Window crosses midnight, e.g. 18:55-24:05 == "18:55 today .. 00:05
        # tomorrow". now is in-window if it's at/after start today, OR at/
        # before the wrapped end time early tomorrow.
        return now_min >= start_min or now_min <= (end_min - 24 * 60)
    return start_min <= now_min <= end_min


# --------------------------------------------------------------------------
# Networking + logging
# --------------------------------------------------------------------------


def fetch_one(url: str, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> tuple[bool, int, str]:
    """Returns (success, http_status, x-vercel-cache-header-or-error-detail)."""
    req = urllib.request.Request(url, headers={"User-Agent": "MEGRIBI-warm-cdn-local/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            cache_hdr = resp.headers.get("x-vercel-cache", "")
            return True, resp.status, cache_hdr
    except urllib.error.HTTPError as exc:
        cache_hdr = exc.headers.get("x-vercel-cache", "") if exc.headers else ""
        return False, exc.code, cache_hdr
    except Exception as exc:  # noqa: BLE001 - best-effort warmer, never crash the pass
        return False, 0, str(exc)[:160]


def log_path_for(now_jst: datetime) -> Path:
    log_dir = Path(os.environ.get("WARM_CDN_LOG_DIR") or tempfile.gettempdir())
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / f"warm_cdn_local_{now_jst:%Y%m%d}.log"


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Warm the Vercel CDN cache for meguribi.jp store APIs "
        "(local Task Scheduler replacement/primary for warm-cdn.yml).",
    )
    ap.add_argument(
        "--once",
        action="store_true",
        default=True,
        help="run a single pass and exit (default; the only supported mode "
        "-- recurrence is handled by Task Scheduler, not this process).",
    )
    ap.add_argument("--base-url", default=os.environ.get("WARM_BASE_URL", DEFAULT_BASE_URL))
    ap.add_argument(
        "--sleep",
        type=float,
        default=float(os.environ.get("WARM_SLEEP_SECONDS", str(DEFAULT_SLEEP_SECONDS))),
    )
    args = ap.parse_args(argv)

    now_jst = datetime.now(JST)

    window_start = os.environ.get("WARM_WINDOW_START", DEFAULT_WINDOW_START)
    window_end = os.environ.get("WARM_WINDOW_END", DEFAULT_WINDOW_END)
    if not in_warm_window(now_jst, window_start, window_end):
        print(
            f"[warm_cdn_local] {now_jst:%Y-%m-%d %H:%M} JST is outside the warm window "
            f"({window_start}-{window_end}); exiting without warming."
        )
        return 0

    stores = load_stores()
    if not stores:
        print(f"[warm_cdn_local] {STORES_JSON_PATH} produced 0 stores; aborting.", file=sys.stderr)
        return 1

    base = args.base_url.rstrip("/")
    urls = build_all_urls(base, stores, now_jst)

    log_path = log_path_for(now_jst)
    t0 = time.monotonic()
    ok = 0
    fail = 0
    rate_limited = 0
    failures: list[str] = []

    with log_path.open("a", encoding="utf-8") as log_f:
        log_f.write(f"\n=== pass start {now_jst:%Y-%m-%d %H:%M:%S} JST | {len(urls)} urls | base={base} ===\n")
        for i, item in enumerate(urls):
            success, status, extra = fetch_one(item.url)
            if success and status == 200:
                ok += 1
            else:
                fail += 1
                if status == 429:
                    rate_limited += 1
                failures.append(f"{item.label}({status})")
            log_f.write(f"{item.label}\t{status}\t{extra}\t{item.url}\n")
            if i < len(urls) - 1:
                time.sleep(args.sleep)

    duration = time.monotonic() - t0
    total = len(urls)
    fail_ratio = (fail / total) if total else 0.0
    summary = (
        f"[warm_cdn_local] done: total={total} ok={ok} fail={fail} "
        f"(429={rate_limited}) duration={duration:.1f}s log={log_path}"
    )
    print(summary)
    with log_path.open("a", encoding="utf-8") as log_f:
        log_f.write(summary + "\n")
        if failures:
            shown = failures[:50]
            more = "" if len(failures) <= 50 else f" ...(+{len(failures) - 50} more)"
            log_f.write("failed: " + ", ".join(shown) + more + "\n")

    if fail_ratio > 0.5:
        print(
            f"[warm_cdn_local] ERROR: {fail}/{total} requests failed (>50%) "
            "- possible backend outage.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
