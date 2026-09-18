#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Supabase が止まっている間、「反響」側のワークフローだけを黙らせるゲート。

一次信号と反響（2026-09-18 の再設計。ここがこのファイルの要点）:
  ワークフローを2種類に分ける。

    **一次信号（このゲートを付けない）**
      site-down-watch.yml            … 利用者にデータが出ていない
      check-collection-heartbeat.yml … 収集が止まった
      「止まったこと自体」を知らせる役なので、上流が死んでいる間こそ鳴らなければ
      意味がない。この2本にゲートは無い（2026-09-11 に付けたものを 09-18 に撤去した）。

    **反響（このゲートを付ける9本）**
      check-blend-weights-freeze / check-daily-published / check-weekly-published /
      warm-cdn / train-ml-model / forecast-accuracy-track / build-templates /
      backup-logs / cleanup-old-logs（2ジョブ）
      上流の Supabase が死んでいれば必ず巻き添えで赤くなる側。ここが鳴っても新しい情報は
      1つも増えず、一次信号のメールを埋もれさせるだけ。

  狙いは「1つの原因で11本が毎回メールを出す」構造を恒久的に「2本だけ」にすること。
  うるさいのは平常時のメール（月1〜2通）ではなく**障害中の増幅**
  （1原因 × 11本 × 1日16〜23通）だった。だから黙らせるのは反響だけでよい。

  **全部は黙らせない**理由（2026-09-18 の実測）: LINE 通知は Secrets 未設定とトークン
  失効で1本も届いていない（CLAUDE.md §4 罠12）。つまり GitHub の失敗メールが
  **唯一の通知経路**である。ここで一次信号まで黙らせたら、本当に誰も気づけなくなる。

なぜ「手でコメントアウトして後で戻す」を選ばなかったか:
  このプロジェクトは沈黙死を何度もやっている（1ヶ月放置の三重事故、京都週報の24日間
  無言スキップ、2026-09-05 の3日半）。**戻し忘れが最大のリスク**なので、人手の復旧作業を
  ゼロにする。このゲートは「上流が止まっている署名」を毎回その場で観測して判断するだけで、
  状態をどこにも持たない。上流が戻れば次の実行から自動で通常運転に戻る。

止める条件（QUOTA_GATE_ALWAYS=1 のとき ＝ 反響9本の恒久運用）:
  「Supabase が止まっている署名」を実際に観測したときだけ。日付とは無関係。
  上流が生きていれば、このゲートは何も止めない（＝反響の失敗は従来どおり届く）。

止める条件（QUOTA_GATE_ALWAYS が無いとき ＝ 従来の日付付き挙動）:
  「解除日より前」かつ「署名を観測」の両方。既定の解除日 2026-09-16 は過ぎているので
  事実上オフ。手動での全停止を将来やりたくなったときのために残してある（日付＋変数）。

fail-closed（判定できないときは「止めない」側に倒す）:
  上の条件を満たさないものはすべて paused=false（＝従来どおりアラートが出る）。具体的には
    - 手動実行（GITHUB_EVENT_NAME=workflow_dispatch）… 人が回したものは必ず動かす
    - 署名以外の失敗（タイムアウト・接続拒否・5xx・401/403・200）
    - SUPABASE_URL / SERVICE_ROLE_KEY が無い（＝確認しようがない）
    - 日付モードで、今日（JST）が解除日以降 / 解除日が天井の外 / 日付が読めない
  「判定できなかったから止める」は絶対にやらない。それをやると 2026-09-05 の事故と同じ
  「監視が黙る」失敗を、こちらの手で作り込むことになる。

公開リポジトリであることの扱い:
  GITHUB_STEP_SUMMARY も Actions のログもログイン無しで読める。ここに出すのは
  **HTTP ステータスコードだけ**で、Supabase のホスト名・URL・レスポンス本文は出さない
  （2026-09-09 に _query_failure.py で同種の情報漏れを塞いだばかり。同じ方針を踏襲する）。

環境変数:
  QUOTA_GATE_ALWAYS      "1" なら**解除日に関係なく**署名だけで判断する（反響9本はこれ）。
                         未設定・空・それ以外の値なら従来の日付付き挙動。肯定の値を
                         明示したときだけ効く形にしてあるのは、打ち間違いが「黙る側」へ
                         倒れないようにするため（fail-closed）。
  OPS_QUOTA_PAUSE_UNTIL  日付モードの自動解除日 YYYY-MM-DD（JST基準、**その日を含めて解除**）。
                         未設定なら下の DEFAULT_PAUSE_UNTIL。リポジトリ変数（vars）で
                         上書きできるので、延長にコード変更は要らない。
                         ただし天井あり（DEFAULT_PAUSE_UNTIL + MAX_PAUSE_EXTENSION_DAYS）。
  GITHUB_EVENT_NAME      GHA の起動理由（`${{ github.event_name }}` をそのまま渡す）。
                         `workflow_dispatch` なら**何も見ずに** paused=false。
                         未設定・空ならこの分岐は働かず、従来どおりの判定になる
                         （ローカルで手で走らせても挙動が変わらないようにするため）。
  SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY  署名判定のための1回きりの疎通に使う。
  GITHUB_OUTPUT / GITHUB_STEP_SUMMARY  あれば書き込む（GHA 外では書かずに続行）。

出力: GITHUB_OUTPUT に `paused=true|false`。
終了コード: **常に 0**。このスクリプト自体はジョブを赤くしない
           （止めるか否かの判断は、呼び出し側の `if:` が outputs.paused を見て行う）。

--------------------------------------------------------------------------------
ワークフロー側の書き方（2026-09-18 現在、反響9本がこの形。このまま貼れる）
--------------------------------------------------------------------------------
別ジョブ（`quota-gate` + `needs:`）ではなく、**本体ジョブの先頭ステップ**として置く。
実物は .github/workflows/check-daily-published.yml を見るのが早い。
**一次信号の2本（site-down-watch / check-collection-heartbeat）には付けないこと。**

    permissions:
      contents: read

    jobs:
      <元のジョブ名>:
        runs-on: ubuntu-latest
        steps:
          - name: Checkout
            uses: actions/checkout@v4

          # ── 上流が死んでいる間だけ反響を抑えるゲート ────────────────────────
          # paused=true になるのは「Supabase が止まっている署名」を観測したときだけ。
          # 判定は quota_pause.py 側にあり、このスクリプトは常に exit 0。
          - name: Quota pause gate
            id: quota_gate
            env:
              SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
              SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SERVICE_ROLE_KEY }}
              # このWFは反響側。解除日に関係なく、上流が死んでいる間は抑制する。
              QUOTA_GATE_ALWAYS: "1"
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
import socket
import sys
import urllib.error
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

# 日付モードの既定の自動解除日（JST）。**この日が来たら何があっても止めない**。
# 2026-09-15 前後に Supabase の請求サイクルがリセットされる見込みだったので、その翌日を置いた。
# 既に過ぎているため、日付モードは事実上オフ（反響9本は QUOTA_GATE_ALWAYS 側を使う）。
# 延ばしたいときはリポジトリ変数 OPS_QUOTA_PAUSE_UNTIL を使うこと（この定数を書き換えると
# tests/test_monitor_quota_pause.py の番犬が赤くなる。「気づかないうちに延びていた」を防ぐため）。
DEFAULT_PAUSE_UNTIL = "2026-09-16"

# 解除日の**天井**。既定日からこの日数を超える解除日は採用しない（＝止めない）。
#
# なぜ天井が要るか:
#   日付モードの最大のリスクは「止めたまま戻し忘れる」ことなのに、解除日はリポジトリ変数
#   OPS_QUOTA_PAUSE_UNTIL でいくらでも先に延ばせる。つまり **いちばん怖い失敗モードが、
#   コードの外にある変数1つに丸ごと逃げている**。誰かが障害対応の勢いで 2027-01-01 を
#   入れて忘れれば、対象のワークフローが恒久的に黙り、しかも全部「緑」で終わるので
#   誰も気づけない。この沈黙死はこのプロジェクトが何度もやっている失敗（1ヶ月放置の
#   三重事故、京都週報の24日間無言スキップ、2026-09-05 の3日半）そのもの。
#   そこで「延長は変数でできるが、伸ばせる上限はコード側が握る」形にする。上限を超える
#   指定は黙って切り詰めず**採用しない**（＝通常運転に戻す）。中途半端に効かせるより、
#   アラートが鳴って人が気づくほうが安全だから。
#   本当に30日より長く止めたいなら DEFAULT_PAUSE_UNTIL ごと直す＝レビューと番犬テスト
#   （tests/test_monitor_quota_pause.py）を必ず通ることになる。
#
#   なお QUOTA_GATE_ALWAYS モード（反響9本）には天井が無い。代わりに「上流が止まっている
#   署名を毎回その場で観測する」ことが歯止めになっている——上流が戻れば即座に鳴り始めるし、
#   そもそも一次信号2本は最初から黙らないので、全部が静まり返る状態にはならない。
MAX_PAUSE_EXTENSION_DAYS = 30

# 手動実行を表す GITHUB_EVENT_NAME の値。この値のときはゲートを素通りさせる。
MANUAL_EVENT_NAME = "workflow_dispatch"

# 「解除日を無視して、署名だけで抑制する」モードに入るための環境変数。
QUOTA_GATE_ALWAYS_ENV = "QUOTA_GATE_ALWAYS"

# 上の環境変数を「有効」と読む値。肯定を明示したときだけ効かせる（打ち間違い・空文字は
# 従来モードへ倒れる＝黙る側に倒れない）。
_AFFIRMATIVE = frozenset({"1", "true", "yes", "on"})

# 止める署名その1: HTTP 402（無料枠超過）。2026-09-05 の形。
# 401/403（キー不正・権限）や 5xx（一時障害）は本物の異常なので止めない。
PAUSE_STATUS = 402

# 止める署名その2: Supabase ホストの**名前解決に失敗**した。
#
# なぜ足したか（2026-09-18）: 9/11 に入れたこのゲートは 9/10〜9/12 の2日しか効かなかった。
# Supabase の壊れ方が「402 を返す」から「**ホスト名が引けない**」へ変わったためで、
# 402 以外＝止めない設計のゲートを素通りし、反響9本のメールがまた増幅した
# （9/12〜9/16 の通知がまさにこれ）。urllib ではこの形は
# `urllib.error.URLError` の `reason` が `socket.gaierror` として現れる。
#
# タイムアウト・接続拒否・5xx・401/403 は**従来どおり止めない**。それらは上流が止まって
# いる証拠にならず（ランナー側の一時的な不調でも同じ形になる）、「判定できない＝止めない」
# の原則をここでも守る。名前解決だけを特別扱いするのは、Supabase のプロジェクトが
# 一時停止・削除されたときに必ずこの形になり、かつ一過性の揺らぎでは起きにくいから。
DNS_FAILURE = "dns-failure"

# 疎通は1回だけ・短いタイムアウト。**再試行しない**——「止まっているか」を見るだけなので、
# バックオフで何十秒も待っても判定は変わらないし、ゲートが遅いと全ジョブが遅くなる。
PROBE_TIMEOUT = 10

LOG_PREFIX = "[quota-pause]"

# 抑制中のサマリに必ず添える一文。「黙っている」と「全部が黙っている」を読み違えさせない。
PRIMARY_SIGNAL_NOTE = (
    "抑えているのは反響だけです。一次信号（site-down-watch / check-collection-heartbeat）"
    "にはこのゲートが無く、いつもどおり赤くなります。"
)

# probe は「観測結果」を返す呼び出し可能オブジェクト。
# 返り値は int（HTTP ステータス）/ DNS_FAILURE / None（判定不能）の3種類。
Probe = Callable[[], "int | str | None"]


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


def always_enabled(raw: object) -> bool:
    """QUOTA_GATE_ALWAYS が「有効」か（反響側のワークフローだけが "1" を渡す）。

    肯定の値を明示したときだけ True にする。未設定・空文字・打ち間違いはすべて False ＝
    従来の日付モードで、こちらは既定解除日を過ぎているので事実上オフ。
    つまり**変数を書き損ねても「黙る側」には倒れない**（fail-closed）。
    """
    if not isinstance(raw, str):
        return False
    return raw.strip().lower() in _AFFIRMATIVE


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


def is_down_signature(status: object) -> bool:
    """観測結果が「Supabase が止まっている署名」か。

    真になるのは 402 と名前解決失敗の2つ**だけ**。ここを広げると（例えば 5xx や
    タイムアウトを足すと）、ランナー側の一時的な不調でも反響が黙るようになり、
    「止まっているのか、ゲートが誤爆したのか」が後から分からなくなる。
    """
    return status == PAUSE_STATUS or status == DNS_FAILURE


def signature_text(status: object) -> str:
    """署名を人が読む1行にする（公開ログに出るのでステータス番号と種別だけ）。"""
    if status == DNS_FAILURE:
        return (
            "Supabase のホスト名を解決できません"
            "（プロジェクトの一時停止・削除、または DNS 障害の疑い）"
        )
    return f"Supabase が {PAUSE_STATUS} を返しています"


def probe_status(url: str, key: str, timeout: int = PROBE_TIMEOUT) -> int | str | None:
    """Supabase REST へ最小の1リクエストを投げ、観測結果を返す。

    返り値は3種類:
      int          … HTTP ステータス（402 はここに来る）
      DNS_FAILURE  … ホスト名を解決できなかった（上流が消えている疑い）
      None         … それ以外の失敗（タイムアウト・接続拒否・その他）＝判定不能

    クエリは他の監視スクリプトと同じ `logs` の最新1行（`limit=1`）。中身は使わない
    ——欲しいのは「止まっている署名かどうか」だけで、本文は読むまでもない。
    """
    if _auth_headers is None:
        return None
    q = urllib.parse.urlencode({"select": "ts", "order": "ts.desc", "limit": "1"})
    req = urllib.request.Request(f"{url}/rest/v1/logs?{q}", headers=_auth_headers(key))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status = getattr(r, "status", None)
            return status if isinstance(status, int) else 200
    except urllib.error.HTTPError as exc:
        # HTTPError は URLError の**子**なので必ず先に捕まえる。順番を入れ替えると
        # 402 が下の名前解決判定へ落ちてしまう（そして reason は文字列なので None になる）。
        code = getattr(exc, "code", None)
        return code if isinstance(code, int) else None
    except urllib.error.URLError as exc:
        # urllib は名前解決の失敗を URLError(reason=socket.gaierror) で包む。接続拒否も
        # タイムアウトも同じ URLError なので、**reason の型**まで見ないと区別できない
        # （メッセージ文字列で判定するとランナーの言語・libc 実装で簡単に壊れる）。
        return DNS_FAILURE if isinstance(exc.reason, socket.gaierror) else None
    except Exception as exc:  # noqa: BLE001
        # ここに来るのは urllib 以外の壊れ方。状態を確認できていないので、
        # `.code` を持っていればそれを、無ければ None を返して止めない側へ倒す。
        code = getattr(exc, "code", None)
        return code if isinstance(code, int) else None


def evaluate(
    *,
    until_raw: str,
    today: date,
    has_credentials: bool,
    probe: Probe,
    event_name: str = "",
    always: bool = False,
) -> tuple[bool, list[str]]:
    """止めるか否かを決める本体。返り値 (paused, 人が読む行のリスト)。

    always=True（反響9本）は解除日を見ない。上流が止まっている署名を観測したときだけ止める。
    always=False（従来の日付モード）は「解除日より前」かつ「署名」の両方を要求する。

    どちらのモードでも、Supabase を叩くのは「手動実行でない」「認証情報がある」
    （日付モードならさらに日付の条件を満たす）がすべて成立したときだけ。それ以外は
    probe を**一度も呼ばない**（無駄な通信をしないため、という以上に、「止めないと決めた
    経路ではもう何も見ない」ことをコードの形で保証するため）。

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

    until: date | None = None
    if not always:
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
            "上流が止まっているかどうか確認できないので止めません。",
        ]

    try:
        status = probe()
    except Exception as exc:  # noqa: BLE001
        # probe_status は例外を飲むが、差し替え実装が投げてくる可能性まで含めてここで受ける。
        # 例外メッセージには URL が混じりうるので、公開ログには型名だけを出す。
        return False, [
            f"通常運転: Supabase の状態を確認できませんでした（{type(exc).__name__}）。",
            "上流が止まっている署名を確認できないので止めません。",
        ]

    if is_down_signature(status):
        if always:
            return True, [
                "反響を抑制中（一次信号の site-down-watch / check-collection-heartbeat は"
                "動いています）。",
                f"理由: {signature_text(status)}。上流が止まっている間だけ後続ステップを"
                "スキップし、このジョブは成功として終えます"
                "（＝1つの原因で失敗メールを11本ぶんに増幅させません）。",
                "上流が戻れば次の実行から自動で通常運転に戻ります（人手の復旧作業は不要）。",
            ]
        remaining = (until - today).days if until else 0
        return True, [
            f"一時停止中: {signature_text(status)}。"
            f"{until.isoformat() if until else ''} に自動解除されます（残り {remaining} 日）。",
            "この間だけ後続ステップをスキップし、ジョブは成功として終えます"
            "（＝失敗メールも通知も出ません）。",
            "解除日を過ぎれば、Supabase が直っていなくてもアラートは自動で戻ります。",
            PRIMARY_SIGNAL_NOTE,
        ]

    if status is None:
        return False, [
            "通常運転: Supabase へ到達できませんでした（タイムアウト・通信断など）。",
            "上流が止まっている署名（402 / 名前解決失敗）ではないので止めません。",
        ]

    return False, [
        f"通常運転: Supabase の HTTP ステータスは {status} でした"
        f"（止めるのは {PAUSE_STATUS} と名前解決失敗のときだけです）。",
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
    # 反響側のワークフローだけが `QUOTA_GATE_ALWAYS: "1"` を渡す。一次信号2本には
    # そもそもこのゲート自体が無い。
    always = always_enabled(os.environ.get(QUOTA_GATE_ALWAYS_ENV))

    try:
        paused, lines = evaluate(
            until_raw=raw,
            today=today_jst(),
            has_credentials=bool(url and key),
            event_name=event_name,
            always=always,
            # ラムダにしておくことで、evaluate が「叩かない」と決めた経路では
            # 本当に1バイトも通信しない。
            probe=lambda: probe_status(url, key),
        )
    except Exception as exc:  # noqa: BLE001
        # 予期しない壊れ方をしたときは必ず「止めない」。ゲートのバグで監視が黙るのが
        # いちばん怖い（それは 2026-09-05 の事故そのもの）。例外メッセージは URL を
        # 含みうるので公開ログには型名だけを出す。
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
