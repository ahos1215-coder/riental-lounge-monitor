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
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SELECT = "id,store_id,ts,men,women,total,weather_code,weather_label,temp_c,precip_mm,src_brand"
# Row-count sanity check tolerance: allows for rows inserted by the live 5-min
# collector during the dump window, without masking a real silent truncation
# (the 2026-07-06 incident dumped 1000 of ~1.07M rows -- a ~99.9% shortfall,
# far outside this tolerance).
ROW_COUNT_TOLERANCE = 0.02  # 2%


def _load_env() -> None:
    # Real environment (e.g. GitHub Actions secrets) wins over local files.
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


def _get(endpoint: str, key: str, params: list[tuple[str, str]], retries: int = 4):
    query = endpoint + "?" + urllib.parse.urlencode(params)
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "Accept": "application/json"}
    last = ""
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(query, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            last = f"HTTP {exc.code}"
            # 4xx (other than rate limit) is not retryable
            if exc.code < 500 and exc.code != 429:
                raise SystemExit(f"backup fetch failed: {last} {exc.read().decode()[:200]}")
        except Exception as exc:  # noqa: BLE001
            last = str(exc)[:120]
        if attempt < retries:
            time.sleep(2 * attempt)
    raise SystemExit(f"backup fetch failed after {retries} attempts: {last}")


def _get_exact_row_count(endpoint: str, key: str, retries: int = 4) -> int:
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
        try:
            req = urllib.request.Request(query, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
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
        except Exception as exc:  # noqa: BLE001
            last = str(exc)[:120]
        if attempt < retries:
            time.sleep(2 * attempt)
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
