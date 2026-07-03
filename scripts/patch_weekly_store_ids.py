"""One-off data repair: fix corrupt `store_id` values in Supabase `blog_drafts`
(content_type='weekly') that were written before the fix in
scripts/generate_weekly_insights.py (`_upsert_weekly_report_to_supabase` used to
hardcode `f"ol_{store}"` for EVERY store, which is wrong for slugs whose true
store_id has a different prefix, e.g. 相席屋 `ay_*` slugs).

This script is READ-ONLY by default (dry-run): it prints a table of the rows
whose stored `store_id` disagrees with the value derived from
frontend/src/data/stores.json (the single source of truth since PR #28) and
exits WITHOUT writing anything. Pass --apply to actually PATCH the corrected
rows into Supabase.

Usage:
    python scripts/patch_weekly_store_ids.py           # dry-run (default, safe)
    python scripts/patch_weekly_store_ids.py --apply    # actually write fixes

Requires SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY (env or .env / .env.local in
repo root). Never prints env values.

Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
STORES_JSON_PATH = REPO_ROOT / "frontend" / "src" / "data" / "stores.json"


def _load_env() -> None:
    """Same simple .env / .env.local parser pattern used elsewhere in scripts/
    (see scripts/score_forecasts.py, scripts/snapshot_forecasts.py, scripts/backup_logs.py).
    Never prints values; only sets os.environ if not already set."""
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


def _load_slug_to_store_id_map() -> dict[str, str]:
    if not STORES_JSON_PATH.exists():
        raise SystemExit(f"stores.json not found: {STORES_JSON_PATH}")
    data = json.loads(STORES_JSON_PATH.read_text(encoding="utf-8"))
    mapping: dict[str, str] = {}
    for row in data:
        slug = row.get("slug")
        store_id = row.get("store_id")
        if slug and store_id:
            mapping[slug] = store_id
    return mapping


def _correct_store_id_for_slug(slug: str, mapping: dict[str, str]) -> str | None:
    """Returns the correct store_id for a weekly report's store_slug, or None if
    the slug is unknown (in which case we skip the row rather than guess)."""
    return mapping.get(slug)


def _fetch_weekly_rows(base_url: str, key: str) -> list[dict[str, Any]]:
    """Fetch facts_id, store_slug, store_id for all weekly blog_drafts rows."""
    params = {
        "content_type": "eq.weekly",
        "select": "facts_id,store_slug,store_id",
        "limit": "5000",
    }
    url = f"{base_url}/rest/v1/blog_drafts?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        url,
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if not isinstance(payload, list):
        raise RuntimeError(f"unexpected response shape from blog_drafts fetch: {type(payload)}")
    return payload


def _patch_store_id(base_url: str, key: str, facts_id: str, new_store_id: str) -> None:
    url = f"{base_url}/rest/v1/blog_drafts?facts_id=eq.{urllib.parse.quote(facts_id)}"
    body = json.dumps({"store_id": new_store_id}).encode("utf-8")
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }
    req = urllib.request.Request(url, data=body, headers=headers, method="PATCH")
    with urllib.request.urlopen(req, timeout=30):
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Actually PATCH the corrected rows into Supabase. Default is dry-run (no writes).",
    )
    args = parser.parse_args()

    _load_env()
    base_url = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    key = (
        os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        or os.environ.get("SUPABASE_SERVICE_KEY")
        or ""
    )
    if not base_url or not key:
        raise SystemExit("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required (set in .env.local)")

    mapping = _load_slug_to_store_id_map()
    print(f"[patch-weekly-store-ids] loaded {len(mapping)} slug -> store_id mappings from stores.json")

    rows = _fetch_weekly_rows(base_url, key)
    print(f"[patch-weekly-store-ids] fetched {len(rows)} weekly blog_drafts rows")

    planned: list[tuple[str, str, str, str]] = []  # (facts_id, slug, old_store_id, new_store_id)
    skipped_unknown_slug: list[str] = []

    for row in rows:
        facts_id = row.get("facts_id")
        slug = row.get("store_slug")
        old_store_id = row.get("store_id")
        if not facts_id or not slug:
            continue
        correct = _correct_store_id_for_slug(slug, mapping)
        if correct is None:
            skipped_unknown_slug.append(slug)
            continue
        if correct != old_store_id:
            planned.append((facts_id, slug, old_store_id or "<empty>", correct))

    if skipped_unknown_slug:
        print(
            f"[patch-weekly-store-ids] WARNING: {len(skipped_unknown_slug)} rows skipped "
            f"(store_slug not found in stores.json): {sorted(set(skipped_unknown_slug))}",
            file=sys.stderr,
        )

    if not planned:
        print("[patch-weekly-store-ids] no corrupt store_id values found. Nothing to do.")
        return 0

    print(f"\n[patch-weekly-store-ids] {len(planned)} row(s) need a store_id fix:\n")
    print(f"{'facts_id':<30} {'slug':<20} {'old store_id':<20} -> {'new store_id':<20}")
    print("-" * 100)
    for facts_id, slug, old_store_id, new_store_id in planned:
        print(f"{facts_id:<30} {slug:<20} {old_store_id:<20} -> {new_store_id:<20}")

    if not args.apply:
        print(
            f"\n[patch-weekly-store-ids] DRY RUN — no changes written. "
            f"Re-run with --apply to PATCH these {len(planned)} row(s)."
        )
        return 0

    print(f"\n[patch-weekly-store-ids] --apply passed. Writing {len(planned)} fix(es)...")
    ok_count = 0
    for facts_id, slug, old_store_id, new_store_id in planned:
        try:
            _patch_store_id(base_url, key, facts_id, new_store_id)
            ok_count += 1
        except urllib.error.HTTPError as exc:
            print(f"[patch-weekly-store-ids] FAILED facts_id={facts_id} slug={slug}: HTTP {exc.code}", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001
            print(f"[patch-weekly-store-ids] FAILED facts_id={facts_id} slug={slug}: {exc}", file=sys.stderr)

    print(f"[patch-weekly-store-ids] done: {ok_count}/{len(planned)} row(s) patched successfully.")
    return 0 if ok_count == len(planned) else 1


if __name__ == "__main__":
    raise SystemExit(main())
