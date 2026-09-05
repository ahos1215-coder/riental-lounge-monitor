#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""日次レポートがその日ちゃんと公開されたかを Supabase に問い合わせて判定する。

.github/workflows/check-daily-published.yml から `python scripts/monitor/check_daily_published.py`
として呼ばれる（もとは同ワークフローの YAML ヒアドキュメントに直書きされていた。
テストから触れず grep でも見つけにくかったため、2026-08-19 の整理でここへ移した）。

2026-08-21（外部レビュー F8）: 判定を「件数が閾値以上か」から「期待する店舗 slug 集合が
全部揃っているか」へ変えた。旧実装は各エディション 30 件（既定）あれば緑だったため、
42 店中 12 店が毎日失敗しても検知できなかった（しかも carry-over 行は前日の
target_date のまま残るので、読者には古い記事が出続ける）。今は欠けた店舗名を出力し、
1店でも欠けていれば非ゼロ終了する。

環境変数:
  SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY  必須
  INPUT_DATE     チェック対象日 YYYY-MM-DD（空欄 = JST の現在時刻から18時間引いた日付。
                 理由は resolve_target_date() のコメント）
  MIN_PUBLISHED  各エディションの最低公開数（既定 30）。**下限フロアとして残す**。
                 ワークフローが常に値を渡すため既定値を変えても効かないので、
                 全店必須の判定は下の STRICT_ALL_STORES 側で行う。
  STRICT_ALL_STORES  1（既定）= 期待 slug 集合との差分が1件でもあれば失敗。
                     0 にすると旧挙動（MIN_PUBLISHED のフロアのみ）へ戻す。
  ALLOWED_MISSING_SLUGS  期待集合から外す slug のカンマ区切り（新規店の生成が始まる
                     までの猶予・恒久的に対象外の店など。コード変更なしで誤報を止める）。
  GITHUB_STEP_SUMMARY / GITHUB_OUTPUT  あれば書き込む（GHA 外では書かずに続行）

終了コード: 0 = 全エディションで期待集合が揃っている / 1 = 欠落・不足・設定不備・照会失敗。
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _retry_common import backoff_delay  # noqa: E402
from _stores_common import all_slugs  # noqa: E402
from _supabase_common import auth_headers  # noqa: E402

EDITIONS = ("evening_preview", "late_update")
FETCH_ATTEMPTS = 3
FETCH_BACKOFF_CAP = 30.0
FETCH_TIMEOUT = 30

JST = timezone(timedelta(hours=9))
# 対象日を決めるときに「現在のJST時刻から差し引く」時間数。18 の根拠は resolve_target_date()。
TARGET_DATE_LOOKBACK_HOURS = 18


def resolve_target_date(now: datetime) -> str:
    """チェック対象の「JST の日付」を決める（INPUT_DATE 未指定時）。

    cron は 14:30 UTC（= 23:30 JST）。見たいのは「その日の JST 日付」の日次レポートで、
    GitHub の cron 遅延は必ず後ろへずれる。したがって "遅延しても対象日が翌日へ飛ばない"
    ことが要件になる。

    なぜ18時間引くのか:
      - 定刻 23:30 JST から18時間引くと 05:30 JST（同日）。対象日は当日のまま。
      - 遅延して翌 17:30 JST に走っても、18時間引けば 23:30 JST（当日）でまだ当日を見る。
        つまり **18.5時間の遅延まで対象日が正しい**（境界は翌 18:00 JST）。
      - 手動 workflow_dispatch を翌朝 09:00 JST に打った場合は 15:00 JST（前日）＝前日を
        見る。前夜のレポートを確認したいという意図に沿う。

    旧実装は `datetime.now(timezone.utc)` の UTC 日付をそのまま使っていた。UTC 日付は
    00:00 UTC（= 09:00 JST）で変わるため、許容できる遅延が **9時間30分しかなかった**。
    2026-08-27 に実測で 9時間23分の遅延が起きており、あと7分で対象日が翌日へずれて
    「まだ生成されていない翌日分」を 0/42 と誤検知するところだった（2026-09-06 修正）。
    （さらに旧々実装は UTC+9h だったため、15:00 UTC 以降の遅延実行で日付が翌日へ飛び、
      未生成の当日を 0 件と誤検知していた。2026-07-06 実測）
    """
    return (now.astimezone(JST) - timedelta(hours=TARGET_DATE_LOOKBACK_HOURS)).strftime("%Y-%m-%d")


def expected_slugs() -> list[str]:
    """その日「揃っているべき」店舗 slug（stores.json が正本）。

    ALLOWED_MISSING_SLUGS で個別に除外できる（新規店の初回生成待ちなど）。
    """
    allowed = {
        s.strip() for s in (os.environ.get("ALLOWED_MISSING_SLUGS") or "").split(",") if s.strip()
    }
    return [s for s in all_slugs() if s not in allowed]


def fetch_published_slugs(url: str, key: str, target: str, edition: str) -> set[str]:
    """指定日・指定エディションの「読者に出せる」日次レポートの store_slug 集合。

    フロントと同じ条件（is_published=true かつ error_message is null）で絞る。
    """
    q = urllib.parse.urlencode({
        "content_type": "eq.daily",
        "target_date": f"eq.{target}",
        "edition": f"eq.{edition}",
        "is_published": "eq.true",
        "error_message": "is.null",
        "select": "store_slug",
        "limit": "500",
    })
    req = urllib.request.Request(
        f"{url}/rest/v1/blog_drafts?{q}",
        headers=auth_headers(key, accept_json=True),
    )
    last_err: Exception | None = None
    for attempt in range(1, FETCH_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as r:
                rows = json.loads(r.read().decode("utf-8"))
            if not isinstance(rows, list):
                raise ValueError(f"unexpected response shape: {rows!r}")
            return {row.get("store_slug") for row in rows if row.get("store_slug")}
        except Exception as e:  # noqa: BLE001
            last_err = e
            # 2026-08-18 の Supabase 飽和（544/429）は即時リトライでは抜けられなかったため、
            # 試行の間に指数バックオフを挟む。
            if attempt < FETCH_ATTEMPTS:
                time.sleep(backoff_delay(attempt, FETCH_BACKOFF_CAP))
    print(f"::error::Supabase 照会に失敗: {last_err}")
    sys.exit(1)


def build_detail(
    target: str,
    floor: int,
    results: dict[str, set[str]],
    expected: list[str],
    *,
    strict: bool = True,
) -> tuple[str, list[str]]:
    """サマリ本文と、基準を満たさなかったエディションの一覧を返す。"""
    expected_set = set(expected)
    lines = [
        f"日次レポート公開チェック（{target} JST, 期待={len(expected_set)}店/エディション, "
        f"フロア={floor}, strict={'on' if strict else 'off'}）"
    ]
    missing: list[str] = []
    for edition in EDITIONS:
        published = set(results.get(edition) or set())
        n = len(published)
        lacking = sorted(expected_set - published)
        extra = sorted(published - expected_set)
        ok = (n >= floor) and (not lacking or not strict)
        lines.append(f"- {edition}: {n}/{len(expected_set)} 店 公開 {'OK' if ok else '不足！'}")
        if lacking:
            lines.append(f"  -> 欠落 {len(lacking)} 店: {', '.join(lacking)}")
        if extra:
            # 閉店店舗が残っている等。失敗にはしないが気づけるように出す。
            lines.append(f"  -> 期待外の slug: {', '.join(extra)}")
        if not ok:
            missing.append(f"{edition}={n}" + (f"(欠落:{','.join(lacking)})" if lacking else ""))
    return "\n".join(lines), missing


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

    target = (os.environ.get("INPUT_DATE") or "").strip()
    if not target:
        # INPUT_DATE が明示されていればそちらを尊重する。空欄のときだけ、
        # GHA の遅延に強い「JST 現在時刻 - 18時間」の日付を使う（根拠は resolve_target_date）。
        target = resolve_target_date(datetime.now(timezone.utc))
    floor = int(os.environ.get("MIN_PUBLISHED") or "30")
    strict = (os.environ.get("STRICT_ALL_STORES") or "1").strip() != "0"

    expected = expected_slugs()
    results = {e: fetch_published_slugs(url, key, target, e) for e in EDITIONS}
    detail, missing = build_detail(target, floor, results, expected, strict=strict)

    _append_env_file("GITHUB_STEP_SUMMARY", detail + "\n")
    _append_env_file("GITHUB_OUTPUT", "detail<<EOF\n" + detail + "\nEOF\n")
    print(detail)

    if missing:
        print(f"::error::日次レポートが未公開/不足です（{target}): {', '.join(missing)}")
        return 1
    print("OK: 全エディションで期待する店舗が揃っています。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
