"""Full backup of the Supabase `logs` table to a gzipped NDJSON file.

Why this exists
---------------
`logs` is the irreplaceable source of truth for ALL ML training (~960k rows of
5-minute headcounts that cannot be re-scraped). It has no database-level backup
in this repo and is auto-pruned weekly by cleanup_old_logs.py, so a bad cleanup,
an accidental DELETE, or a Supabase incident would destroy the entire ML
capability with no way to recover. This script produces a portable snapshot
(one JSON object per line, gzipped) that the `backup-logs` GitHub Actions
workflow ENCRYPTS and uploads to a GitHub Release for durable, off-Supabase
storage. See plan/LOGS_BACKUP.md for the backup + restore runbook.

Design notes
------------
- Standard library only (urllib + gzip + json) so the workflow needs no pip step.
- Keyset pagination on the unique `id` column (order=id.asc, id=gt.<cursor>) so it
  walks ~1M rows reliably without offset drift, and streams each page straight to
  the gzip file (bounded memory).
- Read-only: never writes to Supabase.

Usage
-----
    python scripts/backup_logs.py --out logs-backup.ndjson.gz
    python scripts/backup_logs.py --out f.ndjson.gz --page 25000

Requires SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY (env or .env / .env.local).
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# scripts/_retry_common.py（バックオフ計算の共有実装、stdlib のみ）と
# scripts/_supabase_common.py（.env 読み込み）をシブリングとしてベアインポートする。
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _retry_common import backoff_delay  # noqa: E402
from _supabase_common import _load_env  # noqa: E402

SELECT = "id,store_id,ts,men,women,total,weather_code,weather_label,temp_c,precip_mm,src_brand"
# Row-count sanity check tolerance: allows for rows inserted by the live 5-min
# collector during the dump window, without masking a real silent truncation
# (the 2026-07-06 incident dumped 1000 of ~1.07M rows -- a ~99.9% shortfall,
# far outside this tolerance).
ROW_COUNT_TOLERANCE = 0.02  # 2%

# Retry budget. Supabase caps PostgREST responses at 1000 rows/page (db-max-rows),
# so a full dump of the ~1.28M-row logs table needs ~1,300 SEQUENTIAL requests.
# At that request count even a low per-request failure rate is near-certain to hit
# a run, so the budget has to absorb a multi-minute wobble rather than a blip.
#
# 2026-08-18: the 2026-08-09 and -08-16 runs both died with "read operation timed
# out" partway through (the 08-16 run at 184k/1.28M rows). Supabase was returning
# HTTP 500 / 544 DatabaseTimeout / 429 too_many_connections under concurrent batch
# load -- the weekly backup (Sun 21:00 UTC) was overlapping the daily ML training
# job (starts 20:30 UTC, runs 30min-2h15m and itself issues ~1,300 paged fetches
# plus 84 model uploads). The old budget was 4 attempts with sleep(2*attempt) =
# ~12s of tolerance, so one saturated minute killed a 12-minute job.
# Fix: many more attempts, exponential backoff capped at BACKOFF_MAX_SEC, honour
# Retry-After, and treat 429/5xx as retryable. Worst case per page is ~5 minutes
# of waiting before giving up, which is what a saturated pooler needs.
FETCH_RETRIES = int(os.environ.get("BACKUP_FETCH_RETRIES", "10"))
BACKOFF_MAX_SEC = float(os.environ.get("BACKUP_BACKOFF_MAX_SEC", "45"))
REQUEST_TIMEOUT_SEC = float(os.environ.get("BACKUP_REQUEST_TIMEOUT_SEC", "90"))


# backoff_delay は scripts/_retry_common.py の共有実装（上で import 済み）。
# 呼び出し側は cap をキーワードで明示的に渡すこと（旧実装は第2位置引数が
# retry_after だったので、位置引数のままだと retry_after が cap と解釈される）。


def _retry_after_seconds(exc: urllib.error.HTTPError) -> float | None:
    """Parse a Retry-After response header (integer-seconds form) if present."""
    raw = exc.headers.get("Retry-After") if exc.headers else None
    if not raw:
        return None
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        return None


def _get(endpoint: str, key: str, params: list[tuple[str, str]], retries: int = FETCH_RETRIES):
    query = endpoint + "?" + urllib.parse.urlencode(params)
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "Accept": "application/json"}
    last = ""
    for attempt in range(1, retries + 1):
        retry_after = None
        try:
            req = urllib.request.Request(query, headers=headers)
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SEC) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            last = f"HTTP {exc.code}"
            # 4xx other than 429 is a real error (bad auth/query) -- not retryable.
            # 429 (too_many_connections / SlowDown) and 5xx (500, 544 DatabaseTimeout,
            # 502/503/504) are all transient Supabase saturation signals -- retry them.
            if exc.code < 500 and exc.code != 429:
                raise SystemExit(f"backup fetch failed: {last} {exc.read().decode()[:200]}")
            retry_after = _retry_after_seconds(exc)
        except Exception as exc:  # noqa: BLE001
            last = str(exc)[:120]
        if attempt < retries:
            wait = backoff_delay(attempt, cap=BACKOFF_MAX_SEC, retry_after=retry_after)
            print(f"[backup] transient error ({last}); retry {attempt}/{retries} in {wait:.0f}s", flush=True)
            time.sleep(wait)
    raise SystemExit(f"backup fetch failed after {retries} attempts: {last}")


def _get_exact_row_count(endpoint: str, key: str, retries: int = FETCH_RETRIES) -> int:
    """Ask PostgREST for the exact row count via Content-Range, without fetching rows.

    Uses ``Prefer: count=exact`` + ``Range: 0-0`` so the server returns only the
    count in the ``Content-Range: 0-0/<N>`` response header (cheap, no body payload
    of consequence). This is the sanity check against a silent pagination bug like
    the 2026-07-06 incident where the dump stopped after the first page (1,000
    rows) out of ~1.07M and still exited 0.
    """
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
        "Prefer": "count=exact",
        "Range-Unit": "items",
        "Range": "0-0",
    }
    query = endpoint + "?" + urllib.parse.urlencode([("select", "id"), ("limit", "1")])
    last = ""
    for attempt in range(1, retries + 1):
        retry_after = None
        try:
            req = urllib.request.Request(query, headers=headers)
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SEC) as resp:
                content_range = resp.headers.get("Content-Range", "")
                # e.g. "0-0/1074907"
                if "/" in content_range:
                    tail = content_range.split("/")[-1]
                    if tail != "*":
                        return int(tail)
                raise SystemExit(
                    f"could not parse row count from Content-Range header: {content_range!r}"
                )
        except urllib.error.HTTPError as exc:
            last = f"HTTP {exc.code}"
            if exc.code < 500 and exc.code != 429:
                raise SystemExit(f"row-count check failed: {last} {exc.read().decode()[:200]}")
            retry_after = _retry_after_seconds(exc)
        except Exception as exc:  # noqa: BLE001
            last = str(exc)[:120]
        if attempt < retries:
            wait = backoff_delay(attempt, cap=BACKOFF_MAX_SEC, retry_after=retry_after)
            print(f"[backup] row-count transient error ({last}); retry {attempt}/{retries} in {wait:.0f}s", flush=True)
            time.sleep(wait)
    raise SystemExit(f"row-count check failed after {retries} attempts: {last}")


def check_row_count_sane(
    total: int, db_count: int, tolerance: float = ROW_COUNT_TOLERANCE
) -> tuple[bool, int]:
    """Return ``(is_sane, min_acceptable)`` comparing the dumped row count against
    the DB's actual exact count, within ``tolerance`` (fraction, e.g. 0.02 = 2%).

    Pure function (no I/O) so it can be unit-tested without hitting Supabase.
    """
    min_acceptable = int((1 - tolerance) * db_count)
    return total >= min_acceptable, min_acceptable


def main() -> int:
    _load_env()
    ap = argparse.ArgumentParser(description="Full gzipped NDJSON backup of the Supabase logs table")
    ap.add_argument("--out", required=True, help="output path, e.g. logs-backup.ndjson.gz")
    # PostgREST はサーバ側 db-max-rows(既定 1000)で応答行数を頭打ちにする。ページサイズを
    # それより大きくしても 1000 行しか返らないため、1000 に合わせる(大きくしても無意味かつ
    # 巨大クエリは statement timeout を招く)。終了判定はページ長ではなく空ページで行う(下記)。
    ap.add_argument("--page", type=int, default=1000, help="rows per request (default 1000)")
    args = ap.parse_args()

    url = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    key = (
        os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        or os.environ.get("SUPABASE_SERVICE_KEY")
        or ""
    )
    if not url or not key:
        raise SystemExit("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")
    endpoint = f"{url}/rest/v1/logs"

    out = Path(args.out)
    total = 0
    cursor: object | None = None
    t0 = time.time()
    with gzip.open(out, "wt", encoding="utf-8") as gz:
        while True:
            params: list[tuple[str, str]] = [
                ("select", SELECT),
                ("order", "id.asc"),
                ("limit", str(args.page)),
            ]
            if cursor is not None:
                params.append(("id", f"gt.{cursor}"))
            rows = _get(endpoint, key, params)
            if not isinstance(rows, list) or not rows:
                break
            for row in rows:
                gz.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
            total += len(rows)
            cursor = rows[-1].get("id")
            print(f"[backup] {total:,} rows ...", flush=True)
            # 終了は「空ページ」でのみ判定する(上の `if not rows: break`)。
            # 旧実装は `len(rows) < args.page` でも打ち切っていたが、PostgREST の
            # db-max-rows(1000)で page(旧既定50000)より少ない行数が返るため、
            # 最初の1000行だけで最終ページと誤判定し、107万行中1000行しか
            # バックアップしていなかった(2026-07-06 発覚)。keyset は空ページまで回す。
            if cursor is None:
                break

    size = out.stat().st_size
    print(f"[backup] done: {total:,} rows -> {out} ({size / 1e6:.1f} MB) in {time.time() - t0:.0f}s")
    if total == 0:
        raise SystemExit("backup wrote 0 rows -- refusing to treat an empty dump as success")

    # Row-count sanity check: the 2026-07-06 incident (keyset pagination stopping
    # after the first 1000-row page out of ~1.07M) exited 0 because the only guard
    # was `total == 0`. Compare the dumped row count against the DB's actual exact
    # count (cheap: Content-Range header only, no row payload).
    db_count = _get_exact_row_count(endpoint, key)
    is_sane, min_acceptable = check_row_count_sane(total, db_count)
    print(f"[backup] verify: dumped={total:,} db_count={db_count:,} min_acceptable={min_acceptable:,}")
    if not is_sane:
        raise SystemExit(
            f"backup row-count check failed: dumped {total:,} rows but Supabase reports "
            f"{db_count:,} rows in logs (tolerance {ROW_COUNT_TOLERANCE:.0%}, min acceptable "
            f"{min_acceptable:,}). This looks like a partial/truncated dump -- refusing to "
            f"treat it as a successful backup. Not uploading."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
