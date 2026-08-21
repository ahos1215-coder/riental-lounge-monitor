#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""週次レポートが公開されているか・古すぎないかを Supabase に問い合わせて判定する。

.github/workflows/check-weekly-published.yml から
`python scripts/monitor/check_weekly_published.py` として呼ばれる（もとは同ワークフローの
YAML ヒアドキュメントに直書きされていた）。

2026-08-21（外部レビュー F8）: 判定を「distinct 店舗数 >= 38 かつ**全体の最新1件**が
8日以内」から「期待する店舗 slug 集合それぞれについて、公開済みか・その店の最新更新が
何日前か」へ変えた。旧実装は 41 店が何週も古くても、1 店だけ新しければ緑になれた
（最新1件だけを見ていたため）。今は欠けた店舗名・古い店舗名を出力し、1店でも該当すれば
非ゼロ終了する。

環境変数:
  SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY  必須
  MIN_STORES           公開済みとみなす最低店舗数（既定 38）。**下限フロアとして残す**。
                       ワークフローが常に値を渡すため既定値を変えても効かないので、
                       全店必須の判定は下の STRICT_ALL_STORES 側で行う。
  MAX_STALENESS_DAYS   その店の最新更新がこれより古ければ失敗扱い（既定 8 日）
  STRICT_ALL_STORES    1（既定）= 期待 slug 集合の欠落・店舗別の陳腐化が1件でもあれば失敗。
                       0 にすると旧挙動（店舗数フロア + 全体の最新1件のみ）へ戻す。
  ALLOWED_MISSING_SLUGS  期待集合から外す slug のカンマ区切り（新規店の初回生成待ちなど）。
  GITHUB_STEP_SUMMARY / GITHUB_OUTPUT  あれば書き込む（GHA 外では書かずに続行）

終了コード: 0 = 基準を満たす / 1 = 欠落・陳腐化・不足・設定不備・照会失敗。
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
from _stores_common import all_slugs  # noqa: E402
from _supabase_common import auth_headers  # noqa: E402

FETCH_ATTEMPTS = 3
FETCH_BACKOFF_CAP = 30.0
FETCH_TIMEOUT = 30
STALE_LIST_MAX = 10  # サマリに列挙する店舗名の上限（多すぎると通知が読めない）


def expected_slugs() -> list[str]:
    """その週「揃っているべき」店舗 slug（stores.json が正本）。

    ALLOWED_MISSING_SLUGS で個別に除外できる（新規店の初回生成待ちなど）。
    """
    allowed = {
        s.strip() for s in (os.environ.get("ALLOWED_MISSING_SLUGS") or "").split(",") if s.strip()
    }
    return [s for s in all_slugs() if s not in allowed]


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
        headers=auth_headers(key),
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


def _parse_dt(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def newest_updated_at(rows: list[dict]) -> datetime | None:
    """行の updated_at のうち最も新しい時刻（tz 付き UTC）。読めない値は無視する。"""
    newest: datetime | None = None
    for r in rows:
        dt = _parse_dt(r.get("updated_at"))
        if dt is None:
            continue
        if newest is None or dt > newest:
            newest = dt
    return newest


def newest_by_slug(rows: list[dict]) -> dict[str, datetime]:
    """店舗 slug ごとの最新 updated_at（読めない値・slug 無しの行は無視する）。"""
    out: dict[str, datetime] = {}
    for r in rows:
        slug = r.get("store_slug")
        dt = _parse_dt(r.get("updated_at"))
        if not slug or dt is None:
            continue
        if slug not in out or dt > out[slug]:
            out[slug] = dt
    return out


def build_detail(
    rows: list[dict],
    *,
    min_stores: int,
    max_staleness_days: float,
    now: datetime,
    expected: list[str],
    strict: bool = True,
) -> tuple[str, list[str]]:
    """サマリ本文と、見つかった問題の一覧を返す。"""
    expected_set = set(expected)
    per_slug = newest_by_slug(rows)
    distinct_stores = {r.get("store_slug") for r in rows if r.get("store_slug")}
    store_count = len(distinct_stores)

    newest = newest_updated_at(rows)
    staleness_days = None
    if newest is not None:
        staleness_days = (now - newest).total_seconds() / 86400.0

    missing = sorted(expected_set - set(per_slug))
    stale: list[tuple[str, float]] = []
    for slug in sorted(expected_set & set(per_slug)):
        age = (now - per_slug[slug]).total_seconds() / 86400.0
        if age > max_staleness_days:
            stale.append((slug, age))
    extra = sorted(set(per_slug) - expected_set)

    lines = [
        f"週次レポート公開チェック（期待={len(expected_set)}店, フロア={min_stores}店, "
        f"鮮度基準={max_staleness_days}日以内, strict={'on' if strict else 'off'}）"
    ]
    lines.append(f"- 公開済み店舗数（distinct store_slug）: {store_count} 件")
    if newest is not None:
        lines.append(f"- 最新更新（全体）: {newest.isoformat()} （{staleness_days:.1f} 日前）")
    else:
        lines.append("- 最新更新（全体）: 取得できませんでした（該当レコード無し）")

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

    # ここからが F8 の本体: 「全体の最新1件」ではなく店舗ごとに見る。
    if missing:
        shown = ", ".join(missing[:STALE_LIST_MAX]) + (" ほか" if len(missing) > STALE_LIST_MAX else "")
        lines.append(f"- 未公開の店舗: {len(missing)} 件 -> {shown}")
        if strict:
            problems.append(f"missing={len(missing)}({','.join(missing[:STALE_LIST_MAX])})")
    else:
        lines.append("- 未公開の店舗: なし")

    if stale:
        shown = ", ".join(f"{s}({age:.1f}d)" for s, age in stale[:STALE_LIST_MAX])
        lines.append(
            f"- 陳腐化した店舗（{max_staleness_days}日超）: {len(stale)} 件 -> {shown}"
            + (" ほか" if len(stale) > STALE_LIST_MAX else "")
        )
        if strict:
            problems.append(f"stale_stores={len(stale)}({','.join(s for s, _ in stale[:STALE_LIST_MAX])})")
    else:
        lines.append("- 陳腐化した店舗: なし")

    if extra:
        # 閉店店舗が残っている等。失敗にはしないが気づけるように出す。
        lines.append(f"- 期待外の slug: {', '.join(extra[:STALE_LIST_MAX])}")

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
    strict = (os.environ.get("STRICT_ALL_STORES") or "1").strip() != "0"

    rows = fetch_rows(url, key)
    if not isinstance(rows, list):
        print(f"::error::予期しないレスポンス形式: {rows!r}")
        return 1

    detail, problems = build_detail(
        rows,
        min_stores=min_stores,
        max_staleness_days=max_staleness_days,
        now=datetime.now(timezone.utc),
        expected=expected_slugs(),
        strict=strict,
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
