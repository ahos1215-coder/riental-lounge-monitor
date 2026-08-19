#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""週次レポートが公開されているか・古すぎないかを Supabase に問い合わせて判定する。

.github/workflows/check-weekly-published.yml から
`python scripts/monitor/check_weekly_published.py` として呼ばれる（もとは同ワークフローの
YAML ヒアドキュメントに直書きされていた）。判定ロジック・環境変数名・出力文言・
終了コードは移設前と同じ。

環境変数:
  SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY  必須
  MIN_STORES           公開済みとみなす最低店舗数（既定 38 / 全42店）
  MAX_STALENESS_DAYS   最新更新がこれより古ければ失敗扱い（既定 8 日）
  GITHUB_STEP_SUMMARY / GITHUB_OUTPUT  あれば書き込む（GHA 外では書かずに続行）

終了コード: 0 = 基準を満たす / 1 = 不足・陳腐化・設定不備・照会失敗。
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _retry_common import backoff_delay  # noqa: E402

FETCH_ATTEMPTS = 3
FETCH_BACKOFF_CAP = 30.0
FETCH_TIMEOUT = 30


def fetch_rows(url: str, key: str) -> list[dict]:
    """公開済み weekly レコードの store_slug / updated_at を取得する。"""
    # is_published=true かつ error_message が無い weekly レコードを
    # store_slug, updated_at だけ取得する（全42店なので limit は余裕を持たせる）。
    q = urllib.parse.urlencode({
        "content_type": "eq.weekly",
        "is_published": "eq.true",
        "error_message": "is.null",
        "select": "store_slug,updated_at",
        "order": "updated_at.desc",
        "limit": "200",
    })
    req = urllib.request.Request(
        f"{url}/rest/v1/blog_drafts?{q}",
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
    )
    last_err: Exception | None = None
    for attempt in range(1, FETCH_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            last_err = e
            # 2026-08-18 の Supabase 飽和（544/429）は即時リトライでは抜けられなかったため、
            # 試行の間に指数バックオフを挟む。
            if attempt < FETCH_ATTEMPTS:
                time.sleep(backoff_delay(attempt, FETCH_BACKOFF_CAP))
    print(f"::error::Supabase 照会に失敗: {last_err}")
    sys.exit(1)


def newest_updated_at(rows: list[dict]) -> datetime | None:
    """行の updated_at のうち最も新しい時刻（tz 付き UTC）。読めない値は無視する。"""
    newest: datetime | None = None
    for r in rows:
        raw = r.get("updated_at")
        if not raw:
            continue
        text = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if newest is None or dt > newest:
            newest = dt
    return newest


def build_detail(
    rows: list[dict],
    *,
    min_stores: int,
    max_staleness_days: float,
    now: datetime,
) -> tuple[str, list[str]]:
    """サマリ本文と、見つかった問題の一覧を返す。"""
    distinct_stores = {r.get("store_slug") for r in rows if r.get("store_slug")}
    store_count = len(distinct_stores)

    newest = newest_updated_at(rows)
    staleness_days = None
    if newest is not None:
        staleness_days = (now - newest).total_seconds() / 86400.0

    lines = [f"週次レポート公開チェック（基準={min_stores}店舗以上, 鮮度基準={max_staleness_days}日以内）"]
    lines.append(f"- 公開済み店舗数（distinct store_slug）: {store_count} 件")
    if newest is not None:
        lines.append(
            f"- 最新更新: {newest.isoformat()} "
            f"（{staleness_days:.1f} 日前）"
        )
    else:
        lines.append("- 最新更新: 取得できませんでした（該当レコード無し）")

    problems: list[str] = []
    if store_count < min_stores:
        lines.append(f"  -> 不足！ ({store_count} < {min_stores})")
        problems.append(f"store_count={store_count}<{min_stores}")
    else:
        lines.append("  -> OK")

    if staleness_days is None:
        lines.append("  -> 判定不能（更新日時が取得できません）")
        problems.append("newest_updated_at unavailable")
    elif staleness_days > max_staleness_days:
        lines.append(f"  -> 陳腐化！ ({staleness_days:.1f} > {max_staleness_days} 日)")
        problems.append(f"staleness_days={staleness_days:.1f}>{max_staleness_days}")
    else:
        lines.append("  -> OK")

    return "\n".join(lines), problems


def _append_env_file(env_name: str, text: str) -> None:
    """GHA が用意するファイル（GITHUB_STEP_SUMMARY 等）に追記する。無ければ何もしない。"""
    path = os.environ.get(env_name)
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(text)


def main() -> int:
    url = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or ""
    if not url or not key:
        print("::error::SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY secret 未設定")
        return 1

    min_stores = int(os.environ.get("MIN_STORES") or "38")
    max_staleness_days = float(os.environ.get("MAX_STALENESS_DAYS") or "8")

    rows = fetch_rows(url, key)
    if not isinstance(rows, list):
        print(f"::error::予期しないレスポンス形式: {rows!r}")
        return 1

    detail, problems = build_detail(
        rows,
        min_stores=min_stores,
        max_staleness_days=max_staleness_days,
        now=datetime.now(timezone.utc),
    )

    _append_env_file("GITHUB_STEP_SUMMARY", detail + "\n")
    _append_env_file("GITHUB_OUTPUT", "detail<<EOF\n" + detail + "\nEOF\n")
    print(detail)

    if problems:
        print(f"::error::週次レポートが未公開/不足/陳腐化の可能性があります: {', '.join(problems)}")
        return 1
    print("OK: 週次レポートは基準を満たしています。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
