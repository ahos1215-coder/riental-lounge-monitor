"""
Supabase logs テーブルの容量管理スクリプト。

2段階の防御:
  1. ダウンサンプリング: 1年超のデータを 30分間隔に間引く
  2. 緊急削除: 行数上限（デフォルト300万行）を超えたら最古から削除

Usage:
    python scripts/cleanup_old_logs.py                    # dry-run（確認のみ）
    python scripts/cleanup_old_logs.py --execute          # 実行
    python scripts/cleanup_old_logs.py --execute --max-rows 2000000

環境変数:
    SUPABASE_URL                  (必須)
    SUPABASE_SERVICE_ROLE_KEY     (必須)
    LOGS_MAX_ROWS                 行数上限（デフォルト 3000000）
    LOGS_DOWNSAMPLE_AFTER_DAYS    ダウンサンプリング対象（デフォルト 365日）
    LOGS_DOWNSAMPLE_MINUTES       間引き間隔（デフォルト 30分）
    LOGS_EMERGENCY_DELETE_BATCH   緊急削除のバッチサイズ（デフォルト 10000）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

MAX_ROWS = int(os.getenv("LOGS_MAX_ROWS", "3000000"))
DOWNSAMPLE_AFTER_DAYS = int(os.getenv("LOGS_DOWNSAMPLE_AFTER_DAYS", "365"))
DOWNSAMPLE_MINUTES = int(os.getenv("LOGS_DOWNSAMPLE_MINUTES", "30"))
EMERGENCY_DELETE_BATCH = int(os.getenv("LOGS_EMERGENCY_DELETE_BATCH", "10000"))


def _headers() -> dict[str, str]:
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }


def _rest_get(path: str, params: dict | None = None) -> list[dict]:
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    if params:
        url += "?" + urlencode(params)
    req = Request(url, headers={**_headers(), "Prefer": "return=representation"})
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _rest_delete(path: str, params: dict) -> int:
    url = f"{SUPABASE_URL}/rest/v1/{path}?" + urlencode(params)
    headers = {**_headers(), "Prefer": "return=representation,count=exact"}
    req = Request(url, method="DELETE", headers=headers)
    with urlopen(req, timeout=60) as resp:
        content_range = resp.headers.get("Content-Range", "")
        # Content-Range: */N or 0-M/N
        if "/" in content_range:
            return int(content_range.split("/")[-1]) if content_range.split("/")[-1] != "*" else 0
        body = resp.read()
        try:
            return len(json.loads(body))
        except Exception:
            return 0


def get_row_count() -> int:
    """logs テーブルの行数を取得（count=exact ヘッダー使用）。"""
    url = f"{SUPABASE_URL}/rest/v1/logs?select=id&limit=1"
    headers = {**_headers(), "Prefer": "count=exact"}
    req = Request(url, headers=headers)
    with urlopen(req, timeout=30) as resp:
        cr = resp.headers.get("Content-Range", "")
        # Content-Range: 0-0/580786
        if "/" in cr:
            total = cr.split("/")[-1]
            if total != "*":
                return int(total)
    return -1


def get_oldest_ts() -> str | None:
    rows = _rest_get("logs", {"select": "ts", "order": "ts.asc", "limit": "1"})
    return rows[0]["ts"] if rows else None


def get_newest_ts() -> str | None:
    rows = _rest_get("logs", {"select": "ts", "order": "ts.desc", "limit": "1"})
    return rows[0]["ts"] if rows else None


def find_downsample_candidates(cutoff_iso: str) -> list[dict]:
    """cutoff より古い行で、同じ store_id + 30分スロットに複数行あるものを検出。"""
    # Supabase REST API では複雑な GROUP BY が直接できないため、
    # 古い行を日付バッチで取得して Python 側で判定する
    rows = _rest_get("logs", {
        "select": "id,ts,store_id",
        "ts": f"lt.{cutoff_iso}",
        "order": "ts.asc",
        "limit": "50000",
    })
    if not rows:
        return []

    # 30分スロットごとにグループ化し、各スロットの最初の行だけ残す
    slots: dict[str, list[dict]] = {}
    for row in rows:
        ts = datetime.fromisoformat(row["ts"].replace("Z", "+00:00"))
        slot_minute = (ts.minute // DOWNSAMPLE_MINUTES) * DOWNSAMPLE_MINUTES
        slot_key = f"{row['store_id']}_{ts.strftime('%Y%m%d%H')}{slot_minute:02d}"
        if slot_key not in slots:
            slots[slot_key] = []
        slots[slot_key].append(row)

    # 各スロットの最初の行以外を削除候補にする
    to_delete: list[dict] = []
    for slot_rows in slots.values():
        if len(slot_rows) > 1:
            to_delete.extend(slot_rows[1:])  # 最初の1行は残す
    return to_delete


def delete_by_ids(ids: list[str], dry_run: bool) -> int:
    """指定 ID の行を削除。"""
    if not ids:
        return 0
    if dry_run:
        return len(ids)

    deleted = 0
    # バッチで削除（Supabase REST の URL 長制限を避ける）
    batch_size = 500
    for i in range(0, len(ids), batch_size):
        batch = ids[i:i + batch_size]
        id_filter = ",".join(batch)
        url = f"{SUPABASE_URL}/rest/v1/logs?id=in.({id_filter})"
        req = Request(url, method="DELETE", headers=_headers())
        with urlopen(req, timeout=60) as resp:
            resp.read()
        deleted += len(batch)
    return deleted


def emergency_delete_oldest(current_count: int, max_rows: int, dry_run: bool) -> int:
    """行数上限を超えている場合、最古から削除して上限の 95% まで減らす。"""
    target = int(max_rows * 0.95)  # 5% のバッファを確保
    excess = current_count - target
    if excess <= 0:
        return 0

    print(f"  [emergency] {current_count} rows > {max_rows} limit")
    print(f"  [emergency] deleting oldest {excess} rows (target: {target})")

    if dry_run:
        return excess

    total_deleted = 0
    remaining = excess
    while remaining > 0:
        batch = min(remaining, EMERGENCY_DELETE_BATCH)
        rows = _rest_get("logs", {
            "select": "id",
            "order": "ts.asc",
            "limit": str(batch),
        })
        if not rows:
            break
        ids = [r["id"] for r in rows]
        delete_by_ids(ids, dry_run=False)
        total_deleted += len(ids)
        remaining -= len(ids)
        print(f"  [emergency] deleted batch: {len(ids)}, total: {total_deleted}/{excess}")
    return total_deleted


def main():
    parser = argparse.ArgumentParser(description="Supabase logs cleanup")
    parser.add_argument("--execute", action="store_true", help="Actually delete (default: dry-run)")
    parser.add_argument("--max-rows", type=int, default=MAX_ROWS, help=f"Row limit (default: {MAX_ROWS})")
    parser.add_argument("--skip-downsample", action="store_true", help="Skip downsampling step")
    args = parser.parse_args()

    dry_run = not args.execute

    if not SUPABASE_URL or not SUPABASE_KEY:
        print("[error] SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")
        sys.exit(1)

    print(f"=== Supabase logs cleanup ===")
    print(f"  mode: {'DRY-RUN' if dry_run else 'EXECUTE'}")
    print(f"  max_rows: {args.max_rows:,}")
    print(f"  downsample_after: {DOWNSAMPLE_AFTER_DAYS} days")
    print(f"  downsample_interval: {DOWNSAMPLE_MINUTES} min")
    print()

    # Step 1: 現在の状態
    count = get_row_count()
    oldest = get_oldest_ts()
    newest = get_newest_ts()
    print(f"  current rows: {count:,}")
    print(f"  oldest: {oldest}")
    print(f"  newest: {newest}")
    print(f"  usage: {count / args.max_rows * 100:.1f}% of limit")
    print()

    # Step 2: 緊急削除（行数上限超過時）
    if count > args.max_rows:
        deleted = emergency_delete_oldest(count, args.max_rows, dry_run)
        action = "would delete" if dry_run else "deleted"
        print(f"  [emergency] {action} {deleted:,} oldest rows")
        count -= deleted
        print()

    # Step 3: ダウンサンプリング（1年超のデータ）
    if not args.skip_downsample:
        cutoff = datetime.now(timezone.utc) - timedelta(days=DOWNSAMPLE_AFTER_DAYS)
        cutoff_iso = cutoff.isoformat()
        print(f"  [downsample] checking rows older than {cutoff_iso[:10]}...")
        candidates = find_downsample_candidates(cutoff_iso)
        if candidates:
            action = "would remove" if dry_run else "removing"
            print(f"  [downsample] {action} {len(candidates):,} redundant rows (keeping 1 per {DOWNSAMPLE_MINUTES}min slot)")
            if not dry_run:
                ids = [c["id"] for c in candidates]
                deleted = delete_by_ids(ids, dry_run=False)
                print(f"  [downsample] deleted {deleted:,} rows")
        else:
            print(f"  [downsample] no redundant rows found (already clean or not enough old data)")
    print()

    # Step 4: 結果サマリ
    if not dry_run:
        final_count = get_row_count()
        print(f"  final rows: {final_count:,}")
        print(f"  usage: {final_count / args.max_rows * 100:.1f}% of limit")
    else:
        print(f"  (dry-run complete — use --execute to apply)")

    print("\ndone.")


if __name__ == "__main__":
    main()
