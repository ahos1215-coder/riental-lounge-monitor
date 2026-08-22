"""
Supabase logs テーブルの容量管理スクリプト。

2段階の防御:
  1. ダウンサンプリング: 1年超のデータを 30分間隔に間引く（先に実行し、余剰を間引いてから）
  2. 緊急削除: 行数上限（デフォルト300万行）を超えたら最古から削除
     ただし ML 学習ウィンドウ（PROTECT_DAYS、既定200日 = train_ml_model.py の
     ML_TRAIN_DAYS=180 + 余裕）より新しい行は「絶対に」削除しない。フロアを守れず
     上限を切れない場合は、安全に消せる分だけ消して大声で警告する。

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
    LOGS_DOWNSAMPLE_SCAN_PAGE     ダウンサンプリング候補探索の1ページ行数
                                   （デフォルト 1000 = PostgREST の db-max-rows と同じ。
                                    backup_logs.py の --page と同じ理由でこれより大きくしても
                                    実際には1000行しか返らない）
    LOGS_DOWNSAMPLE_MAX_SCAN_ROWS 候補探索で1回の実行あたりに走査する行数の上限
                                   （デフォルト 200000。週次cronで複数回に分けて収束させる
                                    安全弁。2026-08-22 総合レビュー対応、詳細は下記コメント参照）
    LOGS_EMERGENCY_DELETE_BATCH   緊急削除のバッチサイズ（デフォルト 10000）
    LOGS_PROTECT_DAYS             緊急削除で絶対に消さない直近日数
                                   （デフォルト 200 = ML_TRAIN_DAYS(180) + 余裕20日。
                                    train_ml_model.py 側の ML_TRAIN_DAYS を変更した場合は
                                    こちらも合わせて見直すこと）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

# scripts/_retry_common.py（バックオフ計算・再試行判定の共有実装、stdlib のみ）と
# scripts/_supabase_common.py（設定解決・認証ヘッダ）をシブリングとしてベアインポートする。
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _retry_common import backoff_delay, is_retryable_status  # noqa: E402
from _supabase_common import _supabase_conf, auth_headers  # noqa: E402

# 【2026-08-19 の統一】旧実装はここだけ `SUPABASE_SERVICE_KEY`（別名キー）を見ておらず、
# 他のバッチが動く環境でもこのスクリプトだけ「キーが無い」で止まりうる状態だった。
# `_supabase_conf()` に寄せて他スクリプトと同じ解決順（ROLE_KEY → SERVICE_KEY）にする。
# 未設定時に空文字になる挙動（main() の明示チェックに委ねる）は従来どおり。
_CONF = _supabase_conf()
SUPABASE_URL, SUPABASE_KEY = _CONF if _CONF else ("", "")

MAX_ROWS = int(os.getenv("LOGS_MAX_ROWS", "3000000"))
DOWNSAMPLE_AFTER_DAYS = int(os.getenv("LOGS_DOWNSAMPLE_AFTER_DAYS", "365"))
DOWNSAMPLE_MINUTES = int(os.getenv("LOGS_DOWNSAMPLE_MINUTES", "30"))
# PostgREST はサーバー側上限（db-max-rows、既定1000）で1リクエストの応答行数を頭打ちに
# するため、旧実装の limit=50000 一発 GET は実際には cutoff より古い最古1000行しか
# 見えていなかった（2026-08-22 総合レビュー対応。検証記録は
# memory/general-review-2026-08-22.md）。scripts/backup_logs.py が2026-07-06の同型事故
# （107万行中1000行しか取れていなかった）の教訓で実装したkeysetページング
# （id.asc + id=gt.<cursor>）をこちらにも移植する（find_downsample_candidates() 参照）。
DOWNSAMPLE_SCAN_PAGE = int(os.getenv("LOGS_DOWNSAMPLE_SCAN_PAGE", "1000"))
# 1回の実行でダウンサンプリング候補探索のために走査する行数の上限（安全弁）。
# ダウンサンプリング対象（365日超）が積み上がり始めるのは2026年11月下旬からの見込みで、
# このスクリプトは週次cronのため、1回で全件を捌けなくても複数回の実行で収束すればよい。
# 既定20万行 = ページ1000行×200回程度のREST呼び出し（backup_logs.py の1回のフル
# バックアップが約1300回のページングであることと比べて十分小さい）。
DOWNSAMPLE_MAX_SCAN_ROWS = int(os.getenv("LOGS_DOWNSAMPLE_MAX_SCAN_ROWS", "200000"))
EMERGENCY_DELETE_BATCH = int(os.getenv("LOGS_EMERGENCY_DELETE_BATCH", "10000"))
# train_ml_model.py の ML_TRAIN_DAYS 既定値(180) + 20日の安全マージン。
# train_ml_model.py は numpy/xgboost/lightgbm/optuna 等の重い依存を持つため、
# ここでは import せず、独立した env 変数 + 定数フォールバックで意図を明示する。
PROTECT_DAYS = int(os.getenv("LOGS_PROTECT_DAYS", "200"))

# Retry budget for every Supabase call in this script.
#
# 2026-08-18: the 2026-08-09 and -08-16 scheduled runs both died ~30s in with an
# unhandled ``urllib.error.HTTPError: HTTP Error 500`` raised from get_row_count()
# (the ``Prefer: count=exact`` call, which makes Postgres count all ~1.28M rows).
# This script had NO retry logic anywhere, so a single transient 500 aborted the
# whole job. Supabase returns 500 / 544 DatabaseTimeout / 429 too_many_connections
# whenever it is saturated by the concurrent batch jobs, and cleanup runs at
# Sun 22:00 UTC -- right on top of the weekly ML training job. Every REST call
# here now goes through _rest_request() with exponential backoff.
CLEANUP_RETRIES = int(os.getenv("LOGS_CLEANUP_RETRIES", "8"))
CLEANUP_BACKOFF_MAX_SEC = float(os.getenv("LOGS_CLEANUP_BACKOFF_MAX_SEC", "45"))


def _rest_request(req: Request, *, what: str, timeout: float = 90.0):
    """Perform a Supabase REST request with retries on transient saturation errors.

    Returns the *already-read* ``(body_bytes, headers)`` so the caller can inspect
    Content-Range without worrying about the connection being closed on retry.
    """
    last = ""
    for attempt in range(1, CLEANUP_RETRIES + 1):
        try:
            with urlopen(req, timeout=timeout) as resp:
                return resp.read(), resp.headers
        except urllib.error.HTTPError as exc:
            last = f"HTTP {exc.code}"
            if not is_retryable_status(exc.code):
                raise
        except Exception as exc:  # noqa: BLE001 - transient network error
            last = f"{type(exc).__name__}: {str(exc)[:100]}"
        if attempt < CLEANUP_RETRIES:
            wait = backoff_delay(attempt, cap=CLEANUP_BACKOFF_MAX_SEC)
            print(f"  [retry] {what}: transient error ({last}); attempt {attempt}/{CLEANUP_RETRIES}, waiting {wait:.0f}s")
            time.sleep(wait)
    raise SystemExit(f"[error] {what} failed after {CLEANUP_RETRIES} attempts: {last}")


def _headers() -> dict[str, str]:
    return {
        **auth_headers(SUPABASE_KEY, content_type=True),
        "Prefer": "return=minimal",
    }


def _rest_get(path: str, params: dict | None = None) -> list[dict]:
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    if params:
        url += "?" + urlencode(params)
    req = Request(url, headers={**_headers(), "Prefer": "return=representation"})
    body, _ = _rest_request(req, what=f"GET {path}")
    return json.loads(body)


def _rest_delete(path: str, params: dict) -> int:
    url = f"{SUPABASE_URL}/rest/v1/{path}?" + urlencode(params)
    headers = {**_headers(), "Prefer": "return=representation,count=exact"}
    req = Request(url, method="DELETE", headers=headers)
    body, resp_headers = _rest_request(req, what=f"DELETE {path}")
    content_range = resp_headers.get("Content-Range", "")
    # Content-Range: */N or 0-M/N
    if "/" in content_range:
        return int(content_range.split("/")[-1]) if content_range.split("/")[-1] != "*" else 0
    try:
        return len(json.loads(body))
    except Exception:
        return 0


def get_row_count() -> int:
    """logs テーブルの行数を取得（count=exact ヘッダー使用）。"""
    url = f"{SUPABASE_URL}/rest/v1/logs?select=id&limit=1"
    headers = {**_headers(), "Prefer": "count=exact"}
    req = Request(url, headers=headers)
    _, resp_headers = _rest_request(req, what="get_row_count (count=exact)")
    cr = resp_headers.get("Content-Range", "")
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


def get_protect_cutoff_iso(protect_days: int = PROTECT_DAYS) -> str:
    """ML 学習ウィンドウ保護のカットオフ（この時刻以降の行は緊急削除で絶対に消さない）。"""
    return (datetime.now(timezone.utc) - timedelta(days=protect_days)).isoformat()


def get_row_count_before(cutoff_iso: str) -> int:
    """cutoff より古い行数を取得（count=exact ヘッダー使用）。"""
    url = f"{SUPABASE_URL}/rest/v1/logs?select=id&ts=lt.{cutoff_iso}&limit=1"
    headers = {**_headers(), "Prefer": "count=exact"}
    req = Request(url, headers=headers)
    _, resp_headers = _rest_request(req, what="get_row_count_before (count=exact)")
    cr = resp_headers.get("Content-Range", "")
    if "/" in cr:
        total = cr.split("/")[-1]
        if total != "*":
            return int(total)
    return -1


def find_downsample_candidates(cutoff_iso: str) -> list[dict]:
    """cutoff より古い行で、同じ store_id + 30分スロットに複数行あるものを検出。

    keyset ページング（id.asc + id=gt.<cursor>、1ページ DOWNSAMPLE_SCAN_PAGE 行）で
    cutoff より古い行を漏れなく走査する。PostgREST の db-max-rows（既定1000）を
    超える limit を1回で投げても頭打ちになって黙って一部しか返らない
    （旧実装 limit=50000 の実害）ため、backup_logs.py と同じ「空ページで終了判定」
    方式を使う。DOWNSAMPLE_MAX_SCAN_ROWS で1回の実行あたりの走査量に上限を設け、
    それを超えて対象が残っている場合は警告した上で今回分だけ処理する（週次cronで
    複数回に分けて収束させる前提。詳細はモジュール先頭のコメント参照）。
    """
    # Supabase REST API では複雑な GROUP BY が直接できないため、
    # 古い行をページングで取得して Python 側で判定する
    rows: list[dict] = []
    cursor: str | None = None
    scanned = 0
    while True:
        params: dict[str, str] = {
            "select": "id,ts,store_id",
            "ts": f"lt.{cutoff_iso}",
            "order": "id.asc",
            "limit": str(DOWNSAMPLE_SCAN_PAGE),
        }
        if cursor is not None:
            params["id"] = f"gt.{cursor}"
        page = _rest_get("logs", params)
        if not page:
            break
        rows.extend(page)
        scanned += len(page)
        cursor = page[-1]["id"]
        if scanned >= DOWNSAMPLE_MAX_SCAN_ROWS:
            print(
                f"  [downsample][WARNING] hit scan cap ({DOWNSAMPLE_MAX_SCAN_ROWS:,} rows); "
                "more candidates older than cutoff may remain unscanned. Re-run this "
                "script again (next weekly cron, or manually) to continue, or raise "
                "LOGS_DOWNSAMPLE_MAX_SCAN_ROWS."
            )
            break

    print(f"  [downsample] scanned {scanned:,} rows older than cutoff")
    if not rows:
        return []

    # 30分スロットごとにグループ化し、各スロットの最初の行（ts昇順で最も早い行）
    # だけ残す。id.asc でページングした行の集合をここで改めて ts でソートするため、
    # ページ境界（=id順）と店内の実データ順（=ts順、通常はほぼ一致）がズレていても
    # 「スロット内で最初に記録された行を残す」という旧実装の意図は変わらない。
    slots: dict[str, list[dict]] = {}
    for row in sorted(rows, key=lambda r: r.get("ts", "")):
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
        _rest_request(req, what=f"delete_by_ids batch {i // batch_size + 1}")
        deleted += len(batch)
    return deleted


def emergency_delete_oldest(
    current_count: int,
    max_rows: int,
    dry_run: bool,
    protect_cutoff_iso: str,
    protected_count: int,
) -> int:
    """行数上限を超えている場合、最古から削除して上限の 95% まで減らす。

    ただし ``protect_cutoff_iso`` より新しい行（ML 学習ウィンドウ内、既定で直近
    PROTECT_DAYS 日）は絶対に削除しない。フロアを守ったままでは目標行数まで
    減らせない場合は、安全に削除できる分だけ削除して大声で警告する
    （例外は投げない＝cleanup 自体は成功させ、運用者に気づかせることを優先する）。
    """
    target = int(max_rows * 0.95)  # 5% のバッファを確保
    excess = current_count - target
    if excess <= 0:
        return 0

    # フロアを守れる最大削除可能数 = 「保護対象より古い行」の総数。
    deletable_before_floor = max(0, current_count - protected_count)
    safe_excess = min(excess, deletable_before_floor)

    print(f"  [emergency] {current_count} rows > {max_rows} limit")
    print(f"  [emergency] deleting oldest {safe_excess} rows (target: {target})")
    print(f"  [emergency] protect_cutoff={protect_cutoff_iso} (protected rows: {protected_count:,})")

    if safe_excess < excess:
        shortfall = excess - safe_excess
        print(
            f"  [emergency][WARNING] cannot reach target without deleting rows newer than "
            f"protect_cutoff ({protect_cutoff_iso}). Would breach ML training window floor by "
            f"{shortfall:,} rows - REFUSING to delete those rows. Row count will remain above "
            f"the 95% target after this run. Investigate MAX_ROWS / PROTECT_DAYS or accept a "
            f"temporarily higher row count."
        )

    if safe_excess <= 0:
        return 0

    if dry_run:
        return safe_excess

    total_deleted = 0
    remaining = safe_excess
    while remaining > 0:
        batch = min(remaining, EMERGENCY_DELETE_BATCH)
        rows = _rest_get("logs", {
            "select": "id",
            "order": "ts.asc",
            "ts": f"lt.{protect_cutoff_iso}",
            "limit": str(batch),
        })
        if not rows:
            break
        ids = [r["id"] for r in rows]
        delete_by_ids(ids, dry_run=False)
        total_deleted += len(ids)
        remaining -= len(ids)
        print(f"  [emergency] deleted batch: {len(ids)}, total: {total_deleted}/{safe_excess}")
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
    print(f"  protect_days (ML window floor): {PROTECT_DAYS} days")
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

    # Step 2: ダウンサンプリング（1年超のデータ）を先に実行し、緊急削除で
    # ML 学習ウィンドウを食う前に古いデータの余剰を間引いておく。
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
                count -= deleted
        else:
            print(f"  [downsample] no redundant rows found (already clean or not enough old data)")
    print()

    # Step 3: 緊急削除（行数上限超過時）。ML 学習ウィンドウ（PROTECT_DAYS）より
    # 新しい行は絶対に削除しない。
    if count > args.max_rows:
        protect_cutoff_iso = get_protect_cutoff_iso()
        # cutoff より古い（= 削除対象になり得る）行数。取得失敗(-1)時は安全側に倒して 0 扱い
        # （＝削除可能行数0 => 緊急削除は何もせず警告のみ、が最も安全）。
        eligible_count = get_row_count_before(protect_cutoff_iso)
        eligible_count = max(eligible_count, 0)
        protected_count = max(count - eligible_count, 0)
        deleted = emergency_delete_oldest(
            count,
            args.max_rows,
            dry_run,
            protect_cutoff_iso=protect_cutoff_iso,
            protected_count=protected_count,
        )
        action = "would delete" if dry_run else "deleted"
        print(f"  [emergency] {action} {deleted:,} oldest rows")
        count -= deleted
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
