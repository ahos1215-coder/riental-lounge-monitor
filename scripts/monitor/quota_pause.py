#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Supabase が 402 を返している間だけ、監視ワークフローのアラートを一時停止するゲート。

なぜ必要か（2026-09-11）:
  2026-09-05 から Supabase が無料プランの cached egress 枠を超え、全リクエストに
  HTTP 402 を返している（詳細は docs/INCIDENT_2026-09-05_SUPABASE_QUOTA.md）。
  Supabase に触る監視・バッチはすべて赤くなり続け、9/9 からの2日間だけで
  GitHub の失敗メールが32通たまった。オーナーは「請求サイクルのリセット（9/15 頃）
  までは無料プランのまま妥協する」と決めたので、それまでの間だけ通知を黙らせたい。

なぜ「手でコメントアウトして後で戻す」を選ばなかったか:
  このプロジェクトは沈黙死を何度もやっている（1ヶ月放置の三重事故、京都週報の24日間
  無言スキップ、今回の3日半）。**戻し忘れが最大のリスク**なので、
    (1) 日付で必ず自動解除される
    (2) 「Supabase が実際に 402 を返している」ときだけ効く
  の2条件を両方満たしたときだけ止める。人手の復旧作業をゼロにするのが設計の要点。

fail-closed（判定できないときは「止めない」側に倒す）:
  止める条件は上の2つを**両方**満たすときだけで、それ以外はすべて paused=false
  （＝従来どおりアラートが出る）。具体的には次のすべてで止めない。
    - 手動実行（GITHUB_EVENT_NAME=workflow_dispatch）… 人が回したものは必ず動かす
    - 今日（JST）が解除日以降        … 期限が来たら何があっても止めない
    - 解除日が上限（既定日＋MAX_PAUSE_EXTENSION_DAYS 日）より先 … 下の「天井」参照
    - 402 以外のステータス（200 / 401 / 403 / 404 / 5xx）
    - タイムアウト・DNS 失敗・その他の例外
    - SUPABASE_URL / SERVICE_ROLE_KEY が無い（＝402 かどうか確認しようがない）
    - OPS_QUOTA_PAUSE_UNTIL が日付として読めない
  「判定できなかったから止める」は絶対にやらない。それをやると今回の事故と同じ
  「監視が黙る」失敗を、こちらの手で作り込むことになる。

公開リポジトリであることの扱い:
  GITHUB_STEP_SUMMARY も Actions のログもログイン無しで読める。ここに出すのは
  **HTTP ステータスコードだけ**で、Supabase のホスト名・URL・レスポンス本文は出さない
  （2026-09-09 に _query_failure.py で同種の情報漏れを塞いだばかり。同じ方針を踏襲する）。

環境変数:
  OPS_QUOTA_PAUSE_UNTIL  自動解除日 YYYY-MM-DD（JST基準、**その日を含めて解除**）。
                         未設定なら下の DEFAULT_PAUSE_UNTIL。リポジトリ変数
                         （vars）で上書きできるので、延長にコード変更は要らない。
                         ただし天井あり（DEFAULT_PAUSE_UNTIL + MAX_PAUSE_EXTENSION_DAYS）。
  GITHUB_EVENT_NAME      GHA の起動理由（`${{ github.event_name }}` をそのまま渡す）。
                         `workflow_dispatch` なら**何も見ずに** paused=false。
                         未設定・空ならこの分岐は働かず、従来どおりの判定になる
                         （ローカルで手で走らせても挙動が変わらないようにするため）。
  SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY  402 判定のための1回きりの疎通に使う。
  GITHUB_OUTPUT / GITHUB_STEP_SUMMARY  あれば書き込む（GHA 外では書かずに続行）。

出力: GITHUB_OUTPUT に `paused=true|false`。
終了コード: **常に 0**。このスクリプト自体はジョブを赤くしない
           （止めるか否かの判断は、呼び出し側の `if:` が outputs.paused を見て行う）。

--------------------------------------------------------------------------------
ワークフロー側の書き方（2026-09-11 現在、11本すべてがこの形。このまま貼れる）
--------------------------------------------------------------------------------
別ジョブ（`quota-gate` + `needs:`）ではなく、**本体ジョブの先頭ステップ**として置く。
実物は .github/workflows/check-daily-published.yml を見るのが早い。

    permissions:
      contents: read

    jobs:
      <元のジョブ名>:
        runs-on: ubuntu-latest
        steps:
          - name: Checkout
            uses: actions/checkout@v4

          # ── Supabase 402 の間だけ黙るゲート（日付で自動解除）────────────────
          # paused=true になるのは「解除日より前」かつ「Supabase が実際に 402」の
          # 両方が成立したときだけ。手動実行と期限後は必ず paused=false。
          # 判定は quota_pause.py 側にあり、このスクリプトは常に exit 0。
          - name: Quota pause gate
            id: quota_gate
            env:
              SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
              SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SERVICE_ROLE_KEY }}
              # 未設定なら scripts/monitor/quota_pause.py の既定日が使われる。
              OPS_QUOTA_PAUSE_UNTIL: ${{ vars.OPS_QUOTA_PAUSE_UNTIL }}
              # 手動実行（workflow_dispatch）は絶対に止めないための材料。
              GITHUB_EVENT_NAME: ${{ github.event_name }}
            run: python3 scripts/monitor/quota_pause.py

          # ── 元からあった各ステップ。**全部**にこの if: を付ける ──────────────
          # paused=true の間だけスキップする。スキップされたステップはジョブを
          # failure にしないので、GitHub の失敗メールも飛ばない。
          # 空文字（ゲート自身が落ちた場合）は 'true' ではないので通常どおり走る。
          - name: <元のステップ名>
            if: steps.quota_gate.outputs.paused != 'true'
            run: ...（既存のまま）...

      # ── 通知ジョブ（あれば）────────────────────────────────────────────────
      notify:
        needs: [<元のジョブ名>]
        # 本体ステップが全部スキップされればジョブは成功なので failure() は偽＝
        # ここも走らない。通知側に手を入れる必要はない。
        if: failure()
        uses: ./.github/workflows/notify-on-failure.yml
        secrets: inherit
        with:
          ...（既存のまま）...
"""

from __future__ import annotations

import os
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from _supabase_common import auth_headers as _auth_headers  # noqa: E402
except Exception:  # noqa: BLE001
    # 共通ヘルパを読めない環境でも「止めない」側に倒れるための保険。
    # None のままなら main は疎通せず paused=false を書く（＝従来どおりアラートが出る）。
    _auth_headers = None  # type: ignore[assignment]

JST = timezone(timedelta(hours=9))

# 既定の自動解除日（JST）。**この日が来たら何があっても止めない**。
# 2026-09-15 前後に Supabase の請求サイクルがリセットされる見込みなので、その翌日を置く。
# 延ばしたいときはリポジトリ変数 OPS_QUOTA_PAUSE_UNTIL を使うこと（この定数を書き換えると
# tests/test_monitor_quota_pause.py の番犬が赤くなる。「気づかないうちに延びていた」を防ぐため）。
DEFAULT_PAUSE_UNTIL = "2026-09-16"

# 解除日の**天井**。既定日からこの日数を超える解除日は採用しない（＝止めない）。
#
# なぜ天井が要るか:
#   このゲートの最大のリスクは「止めたまま戻し忘れる」ことなのに、解除日はリポジトリ変数
#   OPS_QUOTA_PAUSE_UNTIL でいくらでも先に延ばせる。つまり **いちばん怖い失敗モードが、
#   コードの外にある変数1つに丸ごと逃げている**。誰かが障害対応の勢いで 2027-01-01 を
#   入れて忘れれば、11本のワークフローが恒久的に黙り、しかも全部「緑」で終わるので
#   誰も気づけない。この沈黙死はこのプロジェクトが何度もやっている失敗（1ヶ月放置の
#   三重事故、京都週報の24日間無言スキップ、2026-09-05 の3日半）そのもの。
#   そこで「延長は変数でできるが、伸ばせる上限はコード側が握る」形にする。上限を超える
#   指定は黙って切り詰めず**採用しない**（＝通常運転に戻す）。中途半端に効かせるより、
#   アラートが鳴って人が気づくほうが安全だから。
#   本当に30日より長く止めたいなら DEFAULT_PAUSE_UNTIL ごと直す＝レビューと番犬テスト
#   （tests/test_monitor_quota_pause.py）を必ず通ることになる。
MAX_PAUSE_EXTENSION_DAYS = 30

# 手動実行を表す GITHUB_EVENT_NAME の値。この値のときはゲートを素通りさせる。
MANUAL_EVENT_NAME = "workflow_dispatch"

# 止める唯一のステータス。401/403（キー不正・権限）や 5xx（一時障害）は本物の異常なので止めない。
PAUSE_STATUS = 402

# 疎通は1回だけ・短いタイムアウト。**再試行しない**——「止まっているか」を見るだけなので、
# バックオフで何十秒も待っても判定は変わらないし、ゲートが遅いと全ジョブが遅くなる。
PROBE_TIMEOUT = 10

LOG_PREFIX = "[quota-pause]"

# probe は「HTTP ステータス（取れなければ None）」を返す呼び出し可能オブジェクト。
Probe = Callable[[], "int | None"]


def parse_until(raw: object) -> date | None:
    """`YYYY-MM-DD` を date にする。読めなければ None（＝止めない側へ倒す）。

    date.fromisoformat は Python 3.11 以降 "20260916" のような表記も通してしまうため、
    書式を1つに固定できる strptime を使う（リポジトリ変数の打ち間違いを黙って受けない）。
    """
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def ceiling_until() -> date | None:
    """採用できる解除日の上限（既定日 + MAX_PAUSE_EXTENSION_DAYS）。

    既定日そのものが壊れていて読めないときは None を返す。呼び出し側はそれを
    「上限を計算できない＝止めない」に落とす（ここでも fail-closed を貫く）。
    定数から毎回計算するのは、既定日を延ばしたときに天井も一緒に動くようにするため。
    """
    base = parse_until(DEFAULT_PAUSE_UNTIL)
    if base is None:
        return None
    return base + timedelta(days=MAX_PAUSE_EXTENSION_DAYS)


def today_jst(now: datetime | None = None) -> date:
    """今日（JST）。解除日の比較は必ず JST で行う（GHA ランナーの now は UTC）。"""
    moment = now or datetime.now(timezone.utc)
    return moment.astimezone(JST).date()


def probe_status(url: str, key: str, timeout: int = PROBE_TIMEOUT) -> int | None:
    """Supabase REST へ最小の1リクエストを投げ、HTTP ステータスを返す（失敗は None）。

    クエリは他の監視スクリプトと同じ `logs` の最新1行（`limit=1`）。中身は使わない
    ——欲しいのはステータスコードだけで、402 が返っているなら本文は読むまでもない。
    例外はすべて飲み込んで None にする（呼び出し側で「判定不能＝止めない」に落ちる）。
    """
    if _auth_headers is None:
        return None
    q = urllib.parse.urlencode({"select": "ts", "order": "ts.desc", "limit": "1"})
    req = urllib.request.Request(f"{url}/rest/v1/logs?{q}", headers=_auth_headers(key))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status = getattr(r, "status", None)
            return status if isinstance(status, int) else 200
    except Exception as exc:  # noqa: BLE001
        # HTTPError は .code を持つ（402 はここに来る）。それ以外（タイムアウト・DNS・
        # 接続断）は状態を確認できていないので None を返し、止めない側へ倒す。
        code = getattr(exc, "code", None)
        return code if isinstance(code, int) else None


def evaluate(
    *,
    until_raw: str,
    today: date,
    has_credentials: bool,
    probe: Probe,
    event_name: str = "",
) -> tuple[bool, list[str]]:
    """止めるか否かを決める本体。返り値 (paused, 人が読む行のリスト)。

    Supabase を叩くのは「手動実行でない」「解除日より前」「解除日が天井の内側」
    「認証情報がある」がすべて成立したときだけ。それ以外は probe を**一度も呼ばない**
    （無駄な通信をしないため、という以上に、「止めないと決めた経路ではもう何も見ない」
    ことをコードの形で保証するため）。

    event_name は GHA の `github.event_name`。未設定・空なら判定に影響しない
    （＝ローカル実行や、まだ env を渡していないワークフローの挙動を変えない）。
    """
    if event_name.strip().lower() == MANUAL_EVENT_NAME:
        # 手動実行は「人が今すぐ動かしたい」という意思表示なので、ゲートより優先する。
        # ここを入れる前は、workflow_dispatch で回してもゲートに食われて何も起きないまま
        # 緑で終わり、回した人が「動いた」と誤解した。とくに cleanup-old-logs.yml の
        # force=true は「バックアップ確認を意図的にバイパスする逃がし弁」なので、
        # 押しても効かないのに成功と見えるのが最も危ない。Supabase も叩かず即座に外す。
        return False, [
            f"通常運転: 手動実行（{MANUAL_EVENT_NAME}）なので止めません。",
            "手で回したジョブは、Supabase の状態も解除日も見ずに必ず実行します。",
        ]

    until = parse_until(until_raw)
    if until is None:
        return False, [
            "通常運転: 一時停止の解除日を日付として読めませんでした"
            f"（OPS_QUOTA_PAUSE_UNTIL={until_raw!r}、期待する形式 YYYY-MM-DD）。",
            "判定できないので止めません（アラートは従来どおり出ます）。",
        ]

    ceiling = ceiling_until()
    if ceiling is None or until > ceiling:
        # 天井の外＝「止めたまま戻し忘れる」領域。切り詰めずに通常運転へ戻す。
        limit = ceiling.isoformat() if ceiling else "（既定日が読めないため算出不能）"
        return False, [
            "通常運転: 指定された解除日が上限を超えているので止めません"
            f"（指定 {until.isoformat()}、上限 {limit}）。",
            f"上限は既定日 {DEFAULT_PAUSE_UNTIL} から {MAX_PAUSE_EXTENSION_DAYS} 日までです。"
            "これ以上延ばしたい場合は、変数ではなくコード側の既定日を直してください"
            "（止めっぱなしの戻し忘れを防ぐための天井です）。",
        ]

    if today >= until:
        return False, [
            f"通常運転: 一時停止の期限（{until.isoformat()}）を過ぎています"
            f"（今日は JST {today.isoformat()}）。",
            "この日以降は Supabase の状態にかかわらず一切止めません。",
        ]

    if not has_credentials:
        return False, [
            "通常運転: Supabase の認証情報（SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY）がありません。",
            f"{PAUSE_STATUS} かどうか確認できないので止めません。",
        ]

    try:
        status = probe()
    except Exception as exc:  # noqa: BLE001
        # probe_status は例外を飲むが、差し替え実装が投げてくる可能性まで含めてここで受ける。
        # 例外メッセージには URL が混じりうるので、公開ログには型名だけを出す。
        return False, [
            f"通常運転: Supabase の状態を確認できませんでした（{type(exc).__name__}）。",
            f"{PAUSE_STATUS} と確認できないので止めません。",
        ]

    if status == PAUSE_STATUS:
        remaining = (until - today).days
        return True, [
            f"一時停止中: Supabase が {PAUSE_STATUS} を返しています。"
            f"{until.isoformat()} に自動解除されます（残り {remaining} 日）。",
            "この間だけ後続ステップをスキップし、ジョブは成功として終えます"
            "（＝失敗メールも通知も出ません）。",
            "解除日を過ぎれば、Supabase が直っていなくてもアラートは自動で戻ります。",
        ]

    if status is None:
        return False, [
            "通常運転: Supabase へ到達できませんでした（タイムアウト・通信断など）。",
            f"{PAUSE_STATUS} と確認できないので止めません。",
        ]

    return False, [
        f"通常運転: Supabase の HTTP ステータスは {status} でした"
        f"（{PAUSE_STATUS} のときだけ一時停止します）。",
    ]


def _append_env_file(env_name: str, text: str) -> None:
    """GHA が用意するファイル（GITHUB_STEP_SUMMARY 等）に追記する。無ければ何もしない。"""
    path = os.environ.get(env_name)
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(text)


def emit(paused: bool, lines: list[str]) -> None:
    """paused を GITHUB_OUTPUT へ、理由をサマリと標準出力へ。

    ここに書く文字列は公開される（このリポジトリは PUBLIC）。ホスト名・URL・
    レスポンス本文は絶対に載せず、ステータスコードと日付だけにする。
    """
    _append_env_file("GITHUB_OUTPUT", f"paused={'true' if paused else 'false'}\n")
    body = "\n".join(lines)
    _append_env_file("GITHUB_STEP_SUMMARY", body + "\n")
    print(body)


def main() -> int:
    raw = (os.environ.get("OPS_QUOTA_PAUSE_UNTIL") or "").strip() or DEFAULT_PAUSE_UNTIL
    url = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or ""
    # ワークフロー側が `GITHUB_EVENT_NAME: ${{ github.event_name }}` で渡す。
    # 未設定（ローカル実行・未対応のワークフロー）なら空文字＝従来どおりの判定。
    event_name = os.environ.get("GITHUB_EVENT_NAME") or ""

    try:
        paused, lines = evaluate(
            until_raw=raw,
            today=today_jst(),
            has_credentials=bool(url and key),
            event_name=event_name,
            # ラムダにしておくことで、evaluate が「叩かない」と決めた経路では
            # 本当に1バイトも通信しない。
            probe=lambda: probe_status(url, key),
        )
    except Exception as exc:  # noqa: BLE001
        # 予期しない壊れ方をしたときは必ず「止めない」。ゲートのバグで監視が黙るのが
        # いちばん怖い（それは今回の事故そのもの）。例外メッセージは URL を含みうるので
        # 公開ログには型名だけを出す。
        paused = False
        lines = [
            f"通常運転: 一時停止ゲートで予期しないエラーが起きました（{type(exc).__name__}）。",
            "判定できないので止めません（アラートは従来どおり出ます）。",
        ]

    emit(paused, lines)
    # 常に 0。ここを非ゼロにすると、止めたいはずのワークフローをゲート自身が赤くしてしまう。
    return 0


if __name__ == "__main__":
    sys.exit(main())
