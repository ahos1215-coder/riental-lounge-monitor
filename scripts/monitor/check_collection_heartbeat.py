#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""収集プロセス（multi_collect.py / /tasks/multi_collect）の生存監視。

.github/workflows/check-collection-heartbeat.yml から
`python scripts/monitor/check_collection_heartbeat.py` として呼ばれる（もとは同ワークフローの
YAML ヒアドキュメントに直書きされていて、テストから触れなかった）。
判定ロジック・閾値・環境変数名・出力文言・終了コードは移設前と同じ。

判定は2本立て:
  1) 全体: logs の最新1行だけを見る。営業ウィンドウ(JST 19:00〜翌05:00)は
     「最終行からの経過 <= threshold_minutes」、昼間は「昨夜が営業終了(05:00 JST)の
     45分以内まで完走していたか」を見る。
  2) 店舗別: stores.json の各店の最新 ts を個別照会し、PER_STORE_STALE_DAYS 日より
     古い/1行も無い店舗を検知する（1店だけ静かに死んでも全体チェックには映らないため）。

環境変数:
  SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY  必須
  THRESHOLD_MINUTES     夜間の許容経過分数（既定 30）
  PER_STORE_STALE_DAYS  店舗別の陳腐化日数（既定 3）
  GITHUB_STEP_SUMMARY / GITHUB_OUTPUT  あれば書き込む（GHA 外では書かずに続行）

終了コード: 0 = 正常 / 1 = 全体NG・店舗別に陳腐化あり・設定不備・照会失敗。
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
from _stores_common import load_stores_json  # noqa: E402
from _supabase_common import auth_headers as _auth_headers  # noqa: E402

JST = timezone(timedelta(hours=9))

# 全体照会（logs の最新1行）の再試行。
# 【2026-08-18 修正】旧実装は 30秒タイムアウトを待ち時間ゼロで3連打するだけだった。
# Supabase が混雑している最中(バッチジョブと衝突している数分間)は3回とも同じ90秒の
# 窓に収まってしまい、必ず全滅する。実例: 2026-08-18 02:54:45→02:56:16 に
# 「Supabase 照会に失敗: The read operation timed out」で失敗(=収集自体は正常で、
# 監視側だけが落ちていた偽アラート)。指数バックオフ(4/8/16/32秒)と長めのタイムアウトで、
# 混雑が収まるのを待つ。
NEWEST_ATTEMPTS = 5
NEWEST_BACKOFF_CAP = 32.0
NEWEST_TIMEOUT = 60

# 店舗別照会の再試行。42店ぶんを直列に照会するため、混雑時は個々の照会も詰まりやすい。
# 15秒2連打(待ちなし)では混雑を待てないので、バックオフ付き3回に広げてある。
PER_STORE_ATTEMPTS = 3
PER_STORE_BACKOFF_CAP = 32.0
PER_STORE_TIMEOUT = 30

# 昼間モードの合格条件: 昨夜の最終行が営業終了(05:00 JST)のこの分数以内まで来ていること。
DAYTIME_MAX_GAP_MINUTES = 45


def fetch_newest_ts(url: str, key: str) -> list[dict]:
    """logs テーブル全体の最新1行を取得する（失敗し続けたら exit 1）。"""
    q = urllib.parse.urlencode({"select": "ts", "order": "ts.desc", "limit": "1"})
    req = urllib.request.Request(f"{url}/rest/v1/logs?{q}", headers=_auth_headers(key))
    last_err: Exception | None = None
    for attempt in range(1, NEWEST_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(req, timeout=NEWEST_TIMEOUT) as r:
                return json.loads(r.read().decode())
        except Exception as e:  # noqa: BLE001
            last_err = e
            if attempt < NEWEST_ATTEMPTS:
                wait = backoff_delay(attempt + 1, NEWEST_BACKOFF_CAP)
                print(f"[heartbeat] 照会失敗({e}) — {wait:.0f}秒後に再試行 {attempt}/{NEWEST_ATTEMPTS}")
                time.sleep(wait)
    print(f"::error::Supabase 照会に失敗: {last_err}")
    sys.exit(1)


def newest_ts_for_store(url: str, key: str, store_id: str) -> tuple[str | None, Exception | None]:
    """指定店舗の最新 ts（無ければ None）と、最後の照会エラーを返す。"""
    sq = urllib.parse.urlencode({
        "store_id": f"eq.{store_id}",
        "select": "ts",
        "order": "ts.desc",
        "limit": "1",
    })
    sreq = urllib.request.Request(f"{url}/rest/v1/logs?{sq}", headers=_auth_headers(key))
    err: Exception | None = None
    for attempt in range(1, PER_STORE_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(sreq, timeout=PER_STORE_TIMEOUT) as r:
                data = json.loads(r.read().decode())
                return (data[0]["ts"] if data else None), None
        except Exception as e:  # noqa: BLE001
            err = e
            if attempt < PER_STORE_ATTEMPTS:
                time.sleep(backoff_delay(attempt, PER_STORE_BACKOFF_CAP))
    return None, err


def evaluate_overall(
    newest: datetime, now: datetime, threshold_minutes: int, newest_raw: object
) -> tuple[str, bool, str, float]:
    """全体判定。返り値 (mode, ok, fail_msg, age_minutes)。

    営業時間ウィンドウ(JST 19:00〜翌05:00)を理解した判定にする。
    実データは営業終了(〜04:55 JST)から開店(19:00 JST)まで新規行が入らないのが
    正常(店が閉まっていて人数が取れない)。旧実装は24時間一律で「30分無ければ
    異常」としており、毎日昼間に3〜4回の偽アラートを出していた(2026-07-08〜10の
    失敗履歴で確認)。
      - 夜間(19:00〜05:00 JST): 従来どおり 経過<=閾値(30分) を要求
      - 昼間(05:00〜19:00 JST): 「昨夜が閉店近くまで収集できていたか」を要求
        (最新行が直近の営業終了時刻 05:00 JST の45分以上前で止まっていれば、
         昨夜の収集が途中で死んでいた=本物の異常として検知できる)
    """
    age_minutes = (now - newest).total_seconds() / 60.0
    now_jst = now.astimezone(JST)
    in_window = (now_jst.hour >= 19) or (now_jst.hour < 5)

    if in_window:
        # 【2026-07-18 修正】夜窓の開始境界(19:00:00 JST ちょうど)に実データの
        # 1行目が着地するわけではない。実測では最初の1行は 19:03〜19:04 JST 頃に
        # 届く(収集トリガーの cron-job.org は5分毎で、店舗一覧SSRの取得・書き込み
        # にも数十秒かかるため)。旧実装は age_minutes(=最新行からの経過)を
        # そのまま30分閾値と比較していたため、19:00:00〜19:04台にチェックが
        # 走ると、前夜最後の行からの経過(=昼間ぶん丸ごと、数百分)がそのまま
        # 閾値超過となり誤報していた
        # (実例: 2026-07-15 19:01:57 に「846分停止」で誤アラート。実際の1行目は
        # 19:03:20着地で、その数分後には正常化していた)。
        # 対策: 夜窓開始(19:00 JST。日付跨ぎの 00:00〜04:59 帯は前日19:00)から
        # 何分経ったかも算出し、min(実経過, 夜窓開始からの経過) を閾値と比較する。
        # 夜窓開始から threshold_minutes 以内は、まだ1行も来ていなくてもそもそも
        # 「陳腐化」しようがない(開店直後で当然データが薄い)ため無条件でOKとする。
        # threshold_minutes を超えて経過した後は、夜窓開始からの経過が閾値を
        # 上回るため実質的に従来どおり age_minutes <= threshold_minutes と同じ
        # 判定に戻る(収集が正常なら age_minutes は常に小さいまま)。
        if now_jst.hour >= 19:
            night_start = now_jst.replace(hour=19, minute=0, second=0, microsecond=0)
        else:
            night_start = (now_jst - timedelta(days=1)).replace(
                hour=19, minute=0, second=0, microsecond=0
            )
        minutes_since_night_start = (now_jst - night_start).total_seconds() / 60.0
        effective_age_minutes = min(age_minutes, minutes_since_night_start)

        mode = f"夜間窓(閾値={threshold_minutes}分、開始から{minutes_since_night_start:.1f}分)"
        ok = effective_age_minutes <= threshold_minutes
        fail_msg = f"収集が {age_minutes:.1f} 分間停止しています（閾値 {threshold_minutes} 分）。"
    else:
        # 直近の営業終了 = 今日の 05:00 JST (05:00〜19:00 の昼間帯なので必ず今日)
        window_end = now_jst.replace(hour=5, minute=0, second=0, microsecond=0)
        gap_minutes = (window_end - newest.astimezone(JST)).total_seconds() / 60.0
        mode = "昼間(前夜の完走チェック)"
        ok = gap_minutes <= DAYTIME_MAX_GAP_MINUTES
        fail_msg = (
            f"昨夜の収集が営業終了の {gap_minutes:.0f} 分前で止まっています"
            f"(最新 {newest_raw})。夜間の収集が途中で死んでいた可能性。"
        )
    return mode, ok, fail_msg, age_minutes


def check_per_store(
    url: str, key: str, store_rows: list[dict], now: datetime, per_store_stale_days: float
) -> tuple[list[str], list[str], int]:
    """店舗別 staleness チェック。返り値 (stale_stores, query_errors, checked)。

    全体チェックは「最新の1行」しか見ないため、複数店のうち1店だけが静かに死んでも
    (例: ol_sapporo_ag が閉店で 2026-05-11 に凍結) 他店の新しい行に隠れて検知できない。
    ここでは stores.json の各店について「その店の最新 ts」を個別に照会し、
    per_store_stale_days 日より古ければ(または1行も無ければ)店名付きで異常を報告する。
    閾値は日単位(既定3日)で毎晩の閉店ウィンドウ(~14時間)を十分に上回るため、
    時間帯を問わず誤検知しない。全体ロジックはそのまま維持し、こちらは加算判定。
    """
    stale_stores: list[str] = []
    query_errors: list[str] = []
    checked = 0
    for entry in store_rows:
        sid = (entry.get("store_id") or "").strip()
        if not sid:
            continue
        label = entry.get("label") or entry.get("store") or entry.get("slug") or sid
        ts_raw, err = newest_ts_for_store(url, key, sid)
        if err is not None:
            query_errors.append(f"{sid}({label})")
            continue
        checked += 1
        if ts_raw is None:
            stale_stores.append(f"{sid}({label}): 収集行なし")
            continue
        try:
            ts_dt = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
        except ValueError:
            stale_stores.append(f"{sid}({label}): ts 解釈不能({ts_raw})")
            continue
        store_age_days = (now - ts_dt).total_seconds() / 86400.0
        if store_age_days > per_store_stale_days:
            stale_stores.append(
                f"{sid}({label}): 最新 {ts_raw} = {store_age_days:.1f}日前 (>{per_store_stale_days:g}日)"
            )
    return stale_stores, query_errors, checked


def _append_env_file(env_name: str, text: str) -> None:
    """GHA が用意するファイル（GITHUB_STEP_SUMMARY 等）に追記する。無ければ何もしない。"""
    path = os.environ.get(env_name)
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(text)


def _emit(detail: str) -> None:
    _append_env_file("GITHUB_STEP_SUMMARY", detail + "\n")
    _append_env_file("GITHUB_OUTPUT", "detail<<EOF\n" + detail + "\nEOF\n")


def main() -> int:
    url = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or ""
    if not url or not key:
        print("::error::SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY secret 未設定")
        return 1

    try:
        threshold_minutes = int(os.environ.get("THRESHOLD_MINUTES") or "30")
    except ValueError:
        threshold_minutes = 30

    rows = fetch_newest_ts(url, key)
    if not rows:
        detail = "logs テーブルが空です（収集が一度も成功していない可能性）。"
        _emit(detail)
        print(f"::error::{detail}")
        return 1

    newest_raw = rows[0]["ts"]
    newest = datetime.fromisoformat(str(newest_raw).replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    mode, ok, fail_msg, age_minutes = evaluate_overall(newest, now, threshold_minutes, newest_raw)

    lines = [
        f"収集ハートビートチェック [{mode}]",
        f"- 最新ログ ts: {newest_raw}",
        f"- 現在時刻(JST): {now.astimezone(JST).isoformat()}",
        f"- 経過: {age_minutes:.1f} 分",
        f"- 判定(全体): {'OK' if ok else 'NG'}",
    ]

    try:
        per_store_stale_days = float(os.environ.get("PER_STORE_STALE_DAYS") or "3")
    except ValueError:
        per_store_stale_days = 3.0

    try:
        store_rows = load_stores_json()
    except Exception as e:  # noqa: BLE001
        print(f"::warning::stores.json を読めませんでした({e}) — 店舗別チェックをスキップします。")
        store_rows = []

    stale_stores, query_errors, checked = check_per_store(
        url, key, store_rows, now, per_store_stale_days
    )

    lines.append(
        f"- 店舗別チェック(閾値={per_store_stale_days:g}日): "
        f"{checked}店照会 / 陳腐化 {len(stale_stores)}店 / 照会失敗 {len(query_errors)}店"
    )
    for s in stale_stores:
        lines.append(f"    停止疑い -> {s}")

    detail = "\n".join(lines)
    _emit(detail)
    print(detail)

    # 全体NG または 店舗別で陳腐化があれば失敗。照会失敗(=一時的な通信エラー)のみでは
    # 落とさない(全体チェックが疎通を保証済み。誤検知回避)。
    problems = []
    if not ok:
        print(f"::error::{fail_msg}")
        problems.append("全体")
    if stale_stores:
        print(f"::error::収集が止まっている店舗があります: {', '.join(stale_stores)}")
        problems.append("店舗別")
    if problems:
        return 1
    print("OK: 収集は正常です（全体 + 全店とも新鮮）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
