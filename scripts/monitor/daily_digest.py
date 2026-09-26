#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""毎朝1通だけ届く運用ダイジェスト（GitHub の失敗メールを切っても困らないようにする）。

なぜ作ったか（2026-09-18）:
  このプロジェクトの通知は「壊れたときに鳴る」形しか無く、その鳴り方が両極端だった。
    - 平常時: 失敗メールは月1〜2通。ほぼ無音なので、**無音が「正常」なのか
      「監視自体が死んでいる」のか区別できない**（2026-09-05 の3日半はこの形）。
    - 障害時: 1つの原因が11本のワークフローに波及し、1日16〜23通に増幅される。
      本当の原因がその洪水に埋もれる（これが「うるさい」の正体で、頻度ではない）。
  どちらも「1日1回、全部まとめて1通」で解ける。鳴らない日が無いので沈黙が異常だと
  分かり、障害時も通数が増えない（内容が濃くなるだけ）。

なぜ GitHub Actions の日次 cron に置くか:
  2026-09-18 に公開 Actions API で直近の発火を実測したところ、**毎時 cron は 24%、
  2時間毎は 43%** しか発火していなかった一方、**日次 cron の欠落はゼロ**だった
  （ただし予定時刻から 1.5〜5 時間遅れる）。速さが要る監視を GHA に約束させてはいけないが、
  「1日1回は必ず来る」役には日次 cron がいちばん向いている（CLAUDE.md §4 罠5）。
  遅延があるので「09:00 に来なければ異常」とは言えない。**14:00 JST までに来なければ
  ダイジェスト自体の異常**、という基準で運用する（本文の先頭にも毎日書いて出す）。

LINE との関係（2026-09-18 時点の現実）:
  GitHub Secrets に LINE_CHANNEL_ACCESS_TOKEN / LINE_USER_ID が無く、オーナー PC の
  トークンも失効していて、**LINE は1本も届いていない**。どの経路も「未設定ならスキップして
  exit 0」なのでジョブは緑のまま通知だけ消えていた（CLAUDE.md §4 罠12）。
  そこでこのスクリプトは LINE を「届く前提の終着点」に置かない:
    - 未設定なら `::warning::` を出して本文を **GITHUB_STEP_SUMMARY にだけ**書き、exit 0。
      ワークフローを赤くしない（＝メールを増やさない。今は失敗メールが唯一の通知なので、
      新しいワークフローが毎朝赤くなると、唯一の経路を自分でノイズまみれにしてしまう）。
    - トークンが復活したら、何も変えなくてもそのまま届き始める。

壊れ方の設計（どれか1つが取れなくても全部が消えない）:
  8項目それぞれを独立に try/except し、失敗した項目だけを「取得失敗（例外の型名）」の
  1行に落とす。1項目の失敗で本文が丸ごと消えるのがいちばん困る（それは沈黙そのもの）。
  例外メッセージ本文は載せない: urllib の例外文字列は接続先ホスト名や URL を含むことがあり、
  ジョブサマリは公開リポジトリでは誰でも読めるため（oriental/routes/health.py と
  scripts/monitor/quota_pause.py で同じ判断をしている）。型名だけで切り分けには足りる。

公開されることの扱い:
  このリポジトリは PUBLIC。ジョブサマリにも Actions のログにも
  **Supabase のホスト名・URL・トークン・レスポンス本文は出さない**。出すのは
  集計値（件数・バイト数・時間差）と HTTP ステータスだけ。

終了コード: **常に 0**。ダイジェストの生成に失敗してもワークフローを赤くしない
           （赤くする＝メールを1通増やすことなので、この仕組みの目的と正面衝突する）。
           生成に失敗したこと自体は「14:00 までに届かない」という形でオーナーに伝わる。

環境変数:
  GITHUB_TOKEN / GITHUB_REPOSITORY          失敗 run と WF 状態の照会（GITHUB_TOKEN で足りる）
  SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY  収集の鮮度・Storage 合計（無ければ「未設定」）
  LINE_CHANNEL_ACCESS_TOKEN / LINE_USER_ID  LINE 送信（無ければ送らずサマリにだけ書く）
  OPS_QUOTA_PAUSE_UNTIL                     一時停止ゲート（scripts/monitor/quota_pause.py）の解除日
  GITHUB_STEP_SUMMARY                       あれば書き込む（GHA 外では書かずに続行）

使い方:
  python3 scripts/monitor/daily_digest.py             # 本番（GHA）
  python3 scripts/monitor/daily_digest.py --dry-run   # 組み立てて表示するだけ（LINE に触らない）
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:  # 共通ヘルパを読めない最小環境でも「本文が出ない」で終わらせないための保険。
    from _supabase_common import auth_headers, load_env, rest_get_json, supabase_conf
except Exception:  # noqa: BLE001
    auth_headers = None  # type: ignore[assignment]
    load_env = None  # type: ignore[assignment]
    rest_get_json = None  # type: ignore[assignment]
    supabase_conf = None  # type: ignore[assignment]

try:
    # 一時停止ゲートの既定解除日。リポジトリ変数 OPS_QUOTA_PAUSE_UNTIL が未設定でも
    # quota_pause.py はこの既定日で動くので、変数だけを見ていると
    # 「ゲートが効いているのにダイジェストは何も言わない」という穴ができる
    # （＝このプロジェクトが繰り返している沈黙死を、こちらの手で1つ作ることになる）。
    # 読めなければ黙って空文字に倒す（相手の実装に強く縛られないため）。
    from quota_pause import DEFAULT_PAUSE_UNTIL as GATE_DEFAULT_UNTIL
except Exception:  # noqa: BLE001
    GATE_DEFAULT_UNTIL = ""

JST = timezone(timedelta(hours=9))
_WEEKDAY_JA = "月火水木金土日"

LOG_PREFIX = "[daily-digest]"

# 1通あたりの上限。LINE の 1 メッセージは 5000 字まで入るが、**スマホの通知と
# トーク画面で一目で読み切れる量**に自分で絞る。読み切れない通知は結局読まれず、
# 「通知はあるのに気づかない」という今回直したい失敗に戻る。溢れた分はジョブサマリに全部ある。
LINE_MAX_CHARS = 900
MORE_SUFFIX = "…（続きは GitHub のジョブサマリ）"

# LINE 無料プラン（Messaging API）の当月上限。残り枠を切らすと**障害時に1通も送れない**。
LINE_FREE_MONTHLY = 200
# これ以上消費していたら毎朝の定期便は送らない（残りは本当の障害通知のために空けておく）。
# 「毎日の定期便より、鳴るべきときに鳴ること」を優先する。
LINE_SKIP_AT = 180
LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"
LINE_QUOTA_URL = "https://api.line.me/v2/bot/message/quota/consumption"

GITHUB_API = "https://api.github.com"
# 「昨日」の幅。日次 cron は 1.5〜5 時間遅れるので、24時間ちょうどだと遅れた日に
# 前回ぶんとの間に隙間ができて失敗を見落とす。少し重ねて取りこぼしを無くす。
FAILED_RUN_WINDOW_HOURS = 34
# 「成功として扱う」conclusion。これ以外（failure / startup_failure / timed_out /
# action_required / stale、および将来 GitHub が足す未知の値）はすべて失敗として数える。
# 取りこぼすと「✅ 失敗なし」という嘘の全クリアになるので、判定は許可リスト側に置く。
SUCCESSFUL_CONCLUSIONS = frozenset({"success", "skipped", "cancelled", "neutral"})
RUNS_PAGE_SIZE = 100
# 本文に名前を出すワークフローの上限。障害中は1原因で11本が同時に落ちるので、
# 全部並べると 900 字が名前で埋まる。件数の多い順に数本だけ出し、残りは本数で示す。
FAILED_WF_SHOWN = 5

# 意図的に止めてあるワークフロー（緊急時のみ手動で回す。disabled_manually が正常）。
# ここに入れていないと毎朝「止まっている」と言い続け、オオカミ少年になる。
# 本当に検知したいのは **60日無活動による自動無効化**（state=disabled_inactivity）のほう。
INTENTIONALLY_DISABLED = (
    "generate-weekly-insights.yml",
    "trigger-blog-cron.yml",
)

# 本番 Flask（Render）。既に公開ワークフロー・scripts/_ollama_common.py にも書かれている
# 公開 URL なので、ここに置いても新たに漏れるものは無い。ただし**本文には出さない**
# （本文に URL を並べても読む人の役に立たないうえ、載せる情報は少ないほど安全）。
BACKEND_URL = "https://riental-lounge-monitor.onrender.com"
# Render Starter の割り当て（Procfile: 1worker × 8threads で 512MB を分け合う）。
# 2026-09-18 時点の実測 RSS は 389MB（76%）で、余裕は大きくない。
RENDER_MEMORY_LIMIT_MB = 512

# 収集は JST 19:00〜翌05:00 の夜間のみなので、昼間に 14 時間ぶん空くのが正常。
# 24時間を超えたら窓に関係なく異常（oriental/routes/health.py の
# _DEFAULT_MAX_DATA_AGE_SEC と同じ線を採る）。
COLLECTION_STALE_HOURS = 24.0

STORAGE_BUCKET = "ml-models"
# Supabase 無料プランの Storage 容量。2026-09-05 の停止で猶予期間を使い切っているため、
# 次に超えたら警告なしで即 402（公式 Billing FAQ）。%を毎朝見えるようにしておく。
STORAGE_FREE_LIMIT_BYTES = 1024 ** 3
STORAGE_LIST_PAGE = 100
# 列挙の暴走止め。バケットが想定外に育っても、毎朝のダイジェストが何百リクエストも
# 投げて egress を食う側に回らないようにする（この監視が枠を削っては本末転倒）。
STORAGE_MAX_REQUESTS = 40

# 期限の決まっているリスク。出典は docs/FAILURE_MAP.md の「固定日付のリスク（期限つき）」。
#   - Tailscale の認証鍵が失効（オーナー PC への経路が切れる）
#   - ドメインの有効期限
#   - Supabase のログ取り込み枠（月1GB）の適用開始。公式の表現は「猶予は2027年の初めまで」で
#     日付の明示が無いため 2027-01-01 と置く。2026-09 の実測（管理画面）は月1.5GB前後のペースで、
#     何もしなければ枠を超える。無料プランの猶予は 2026-09-05 に使い切っている
# 解決済みで外したもの（期限切れのまま残すと、毎朝「🔴 超過」と嘘をつき続けるため）:
#   - Vercel の Node.js 20 終了（2026-10-01）: 2026-09-26 に frontend/package.json の
#     engines.node を 24.x に固定して解消した（Vercel の仕様で管理画面の設定より優先される）。
#     固定が外れないよう tests/test_frontend_node_engine.py が見張っている。
DEADLINES: tuple[tuple[str, str], ...] = (
    ("Tailscale の鍵が失効", "2026-11-20"),
    ("ドメインの期限", "2026-12-31"),
    ("Supabase のログ枠（月1GB）の適用開始", "2027-01-01"),
)
# 残りこの日数以内になったら本文に出す。
DEADLINE_WARN_DAYS = 30

HTTP_TIMEOUT = 15
USER_AGENT = "megribi-daily-digest/1.0 (+github-actions)"

# 見出し語（短さは 900 字の予算そのもの。増やすときは必ず何かを削ること）。
L_FAILED = "失敗WF"
L_STOPPED = "停止WF"
L_SITE = "サイト"
L_COLLECT = "収集"
L_STORAGE = "Storage"
L_LINE = "LINE"
L_DEADLINE = "期限"
L_PAUSE = "一時停止"


@dataclass
class Digest:
    """組み立て結果。`blocked_reason` が None のときだけ送ってよい。"""

    lines: list[str] = field(default_factory=list)
    blocked_reason: str | None = None

    @property
    def body(self) -> str:
        return "\n".join(self.lines)


# --------------------------------------------------------------------------- #
# 小さな道具
# --------------------------------------------------------------------------- #
def clip_for_line(text: str, limit: int = LINE_MAX_CHARS) -> str:
    """LINE 1通に収まる長さへ切り詰める（切ったことが読み手に分かる形で）。"""
    if len(text) <= limit:
        return text
    # 末尾の目印ごと limit に収める（「切った」と書いてある行がはみ出したら意味が無い）。
    return text[: max(0, limit - len(MORE_SUFFIX))] + MORE_SUFFIX


def _fail_line(label: str, exc: BaseException) -> str:
    """取得に失敗した項目の1行。**例外の型名だけ**を出す（本文は公開ログに載せない）。"""
    return f"{label}: 取得失敗（{type(exc).__name__}）"


def _safe(label: str, fn) -> list[str]:
    """1項目を独立に実行する。失敗しても他の項目を巻き込まない。"""
    try:
        return list(fn())
    except Exception as exc:  # noqa: BLE001 - 1項目の失敗で本文を丸ごと失わないための壁
        return [_fail_line(label, exc)]


def _append_env_file(env_name: str, text: str) -> None:
    """GHA が用意するファイル（GITHUB_STEP_SUMMARY 等）に追記する。無ければ何もしない。"""
    path = os.environ.get(env_name)
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(text)
    except OSError:
        # サマリが書けないだけでダイジェスト本体を落とさない（標準出力には既に出ている）。
        pass


def _configure_stdout_utf8() -> None:
    """Windows の既定コンソール(cp932)で日本語を print しても落ちないようにする
    （CLAUDE.md 罠#9。ローカル `--dry-run` 実行のため）。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            pass


def _get_json(url: str, headers: dict[str, str], timeout: int = HTTP_TIMEOUT):
    """GET して JSON にする（GitHub / LINE / 本番 API 用。Supabase REST は別経路）。

    Supabase の REST だけは `_supabase_common.rest_get_json` を必ず通す規約なので
    ここを使わない（gzip の要求と解凍を1箇所に閉じ込めるため。2026-09-18）。
    """
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **headers})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _github_headers(token: str) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def today_jst(now: datetime | None = None) -> date:
    return (now or datetime.now(timezone.utc)).astimezone(JST).date()


def parse_ymd(raw: object) -> date | None:
    """`YYYY-MM-DD` を date にする。読めなければ None。

    date.fromisoformat は Python 3.11 以降 "20260916" も通すため、書式を1つに
    固定できる strptime を使う（quota_pause.py と同じ判断）。
    """
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return datetime.strptime(raw.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# 1. 昨日の失敗ワークフロー
# --------------------------------------------------------------------------- #
def section_failed_runs(repo: str, token: str, now: datetime) -> list[str]:
    if not repo:
        return [f"{L_FAILED}: 未設定（GITHUB_REPOSITORY）"]
    since = (now - timedelta(hours=FAILED_RUN_WINDOW_HOURS)).astimezone(timezone.utc)
    params = {
        # 2026-09-18 修正: 以前は status=failure でサーバ側を絞っていたが、それだと
        # startup_failure（ワークフロー YAML の破損）と timed_out を1件も拾えなかった。
        # どちらも run は赤くなり失敗メールも飛ぶのに、ダイジェストは「✅ 失敗なし」と
        # 言い切ってしまう＝このダイジェストがいちばんやってはいけない「嘘の全クリア」。
        # 実際このリポジトリには startup_failure の run が実在する（2026-04 の cleanup 2件）。
        # status=completed で引いて、conclusion が SUCCESSFUL_CONCLUSIONS 以外なら失敗と数える
        # （将来 GitHub が新しい conclusion を足しても、拾う側に倒れる）。
        "status": "completed",
        "created": f">={since.strftime('%Y-%m-%dT%H:%M:%SZ')}",
        "per_page": str(RUNS_PAGE_SIZE),
        "exclude_pull_requests": "true",
    }
    data = _get_json(
        f"{GITHUB_API}/repos/{repo}/actions/runs?" + urllib.parse.urlencode(params),
        _github_headers(token),
    )
    runs = data.get("workflow_runs") or []
    counts: dict[str, int] = {}
    for run in runs:
        if not isinstance(run, dict):
            continue
        conclusion = str(run.get("conclusion") or "")
        # 「成功扱いのもの以外は全部失敗」。未知の conclusion も拾う側に倒す。
        if conclusion in SUCCESSFUL_CONCLUSIONS:
            continue
        name = str(run.get("name") or "(名前不明)")
        # failure 以外（startup_failure / timed_out 等）は種別を出す。原因の見当がつく。
        label = name if conclusion == "failure" else f"{name}[{conclusion or '?'}]"
        counts[label] = counts.get(label, 0) + 1

    if not counts:
        return [f"{L_FAILED}: ✅ 失敗なし（過去{int(FAILED_RUN_WINDOW_HOURS)}時間）"]

    total = sum(counts.values())
    # 件数の多い順（同数なら名前順）。障害の中心にいるワークフローを先頭に出す。
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    lines = [f"{L_FAILED}: ❌ {total}件 / {len(counts)}本"]
    for name, count in ranked[:FAILED_WF_SHOWN]:
        lines.append(f"・{name} ×{count}")
    if len(ranked) > FAILED_WF_SHOWN:
        lines.append(f"・ほか{len(ranked) - FAILED_WF_SHOWN}本")
    if len(runs) >= RUNS_PAGE_SIZE:
        # 100 件で頭打ちになった＝実際はもっと多い。過少報告だと気づけるようにしておく。
        lines.append(f"・（{RUNS_PAGE_SIZE}件で打ち切り。実際はもっと多い）")
    return lines


# --------------------------------------------------------------------------- #
# 2. 止まっているワークフロー（60日無活動の自動無効化を拾う）
# --------------------------------------------------------------------------- #
def section_workflow_states(repo: str, token: str) -> list[str]:
    if not repo:
        return [f"{L_STOPPED}: 未設定（GITHUB_REPOSITORY）"]
    data = _get_json(
        f"{GITHUB_API}/repos/{repo}/actions/workflows?per_page=100",
        _github_headers(token),
    )
    stopped: list[tuple[str, str]] = []
    for wf in data.get("workflows") or []:
        if not isinstance(wf, dict):
            continue
        state = str(wf.get("state") or "")
        if state == "active":
            continue
        filename = str(wf.get("path") or "").rsplit("/", 1)[-1]
        if filename in INTENTIONALLY_DISABLED:
            continue
        stopped.append((str(wf.get("name") or filename), state))

    if not stopped:
        return [f"{L_STOPPED}: ✅ なし"]
    lines = [f"{L_STOPPED}: ⚠️ {len(stopped)}本"]
    for name, state in sorted(stopped):
        lines.append(f"・{name}（{state}）")
    return lines


# --------------------------------------------------------------------------- #
# 3. サイトの健全性（/healthz は 2026-09-09 に「正直な healthz」へ改修済み）
# --------------------------------------------------------------------------- #
def section_site_health() -> list[str]:
    # 2026-09-18 修正: 以前はここで例外を上位の _safe に抜けさせ、
    # 「サイト: 取得失敗（HTTPError）」という無印の1行になっていた。
    # しかし oriental/routes/health.py の設計上 /healthz は良し悪しに関わらず**常に200**を返す
    # （暖機と Render のヘルスチェックを兼ねるため意図的にそうしている）。
    # つまり非200・到達不能は「ダイジェストが確認できなかった」ではなく
    # **サイトそのものが落ちている**という、この通知でいちばん重い事実。
    # 他の項目の「取得失敗」と同じ見た目にすると読み飛ばされるので、ここで捕まえて ❌ を付ける。
    try:
        payload = _get_json(f"{BACKEND_URL}/healthz", {})
    except urllib.error.HTTPError as exc:
        return [f"{L_SITE}: ❌ 到達できません（HTTP {exc.code}）"]
    except Exception as exc:  # noqa: BLE001 - URLError・タイムアウト・JSON崩れ等
        # 例外文字列にはホスト名や URL が入りうるので型名だけにする（公開サマリに出るため）。
        return [f"{L_SITE}: ❌ 到達できません（{type(exc).__name__}）"]
    if not isinstance(payload, dict):
        return [f"{L_SITE}: ❌ 想定外の応答"]

    memory = payload.get("memory") or {}
    forecast = payload.get("forecast_model") or {}
    rss = memory.get("rss_mb") if isinstance(memory, dict) else None
    loaded = forecast.get("loaded_store_count") if isinstance(forecast, dict) else None
    problems = payload.get("problems") or []

    # 数値でないものが来ても「サイトの項目が丸ごと消える」にはしない（RSS は添え物で、
    # 本当に読みたいのは ok と problem_detail のほう）。
    if isinstance(rss, bool) or not isinstance(rss, (int, float)):
        mem_text = "RSS不明"
    else:
        pct = float(rss) / RENDER_MEMORY_LIMIT_MB * 100
        mem_text = f"RSS {float(rss):.0f}MB({pct:.0f}%)"
    model_text = f"モデル{loaded}店" if isinstance(loaded, int) else "モデル不明"

    if payload.get("ok"):
        return [f"{L_SITE}: ✅ 正常 / {mem_text} / {model_text}"]

    lines = [f"{L_SITE}: ❌ ok=false / {mem_text} / {model_text}"]
    # problem_detail は health.py 側でホスト名・スキーマを載せない設計（2026-09-09 レビュー）。
    # それでも長さだけは切る（1行に収めて読み飛ばされないようにする）。
    detail = str(payload.get("problem_detail") or "").replace("\n", " ").strip()
    if detail:
        lines.append(f"・{detail[:160]}")
    elif problems:
        lines.append("・" + ", ".join(str(code) for code in problems)[:160])
    return lines


# --------------------------------------------------------------------------- #
# 4. 収集の鮮度（Supabase logs の最新1行）
# --------------------------------------------------------------------------- #
def _supabase_ready() -> tuple[str, str] | None:
    if supabase_conf is None or auth_headers is None or rest_get_json is None:
        return None
    return supabase_conf()


def section_collection_freshness(now: datetime) -> list[str]:
    conf = _supabase_ready()
    if conf is None:
        return [f"{L_COLLECT}: 未設定"]
    base, key = conf
    query = urllib.parse.urlencode({"select": "ts", "order": "ts.desc", "limit": "1"})
    rows = rest_get_json(
        f"{base}/rest/v1/logs?{query}",
        auth_headers(key, accept_json=True),
        timeout=HTTP_TIMEOUT,
    )
    if not isinstance(rows, list) or not rows:
        return [f"{L_COLLECT}: ❌ 1行も取れない（収集停止の疑い）"]
    latest = rows[0].get("ts") if isinstance(rows[0], dict) else None
    if not latest:
        return [f"{L_COLLECT}: ❌ 最新行に ts が無い"]

    text = str(latest)
    moment = datetime.fromisoformat(text.replace("Z", "+00:00") if text.endswith("Z") else text)
    if moment.tzinfo is None:
        # logs の ts は UTC で入る。タイムゾーン無しで返ってきたら UTC とみなす
        # （naive のまま引き算すると TypeError で項目ごと落ちる）。
        moment = moment.replace(tzinfo=timezone.utc)
    hours = (now - moment).total_seconds() / 3600.0

    mark = "✅" if hours <= COLLECTION_STALE_HOURS else "❌"
    return [f"{L_COLLECT}: {mark} 最新データは {hours:.1f} 時間前"]


# --------------------------------------------------------------------------- #
# 5. Storage 合計（無料枠 1GB に対する割合）
# --------------------------------------------------------------------------- #
def _walk_storage(base: str, key: str) -> tuple[int, int, bool]:
    """バケット全体を歩いて (合計バイト, オブジェクト数, 打ち切ったか) を返す。

    Supabase の list API はフォルダ1階層ぶんしか返さず、フォルダは `id: null` の
    エントリとして現れる（`forecast/latest/*` や `accuracy/scores/*` のように
    このバケットは階層を持つ）。深さに制限を設けず幅優先で歩くが、
    リクエスト数には天井を置く（暴走して egress を食わないため）。
    """
    endpoint = f"{base}/storage/v1/object/list/{STORAGE_BUCKET}"
    headers = {**auth_headers(key), "Content-Type": "application/json"}
    pending: list[str] = [""]
    total = 0
    count = 0
    requests_made = 0

    while pending:
        prefix = pending.pop(0)
        offset = 0
        while True:
            if requests_made >= STORAGE_MAX_REQUESTS:
                return total, count, True
            body = json.dumps(
                {
                    "prefix": prefix,
                    "limit": STORAGE_LIST_PAGE,
                    "offset": offset,
                    "sortBy": {"column": "name", "order": "asc"},
                }
            ).encode("utf-8")
            req = urllib.request.Request(
                endpoint, data=body, method="POST", headers={"User-Agent": USER_AGENT, **headers}
            )
            requests_made += 1
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                page = json.loads(resp.read().decode("utf-8"))
            if not isinstance(page, list) or not page:
                break
            for entry in page:
                if not isinstance(entry, dict):
                    continue
                name = entry.get("name")
                if not name:
                    continue
                if entry.get("id") is None:
                    pending.append(f"{prefix}{name}/")
                    continue
                meta = entry.get("metadata") or {}
                size = meta.get("size") if isinstance(meta, dict) else None
                if isinstance(size, bool) or not isinstance(size, (int, float)):
                    size = (meta.get("contentLength") if isinstance(meta, dict) else 0) or 0
                try:
                    total += int(size)
                except (TypeError, ValueError):
                    pass
                count += 1
            if len(page) < STORAGE_LIST_PAGE:
                break
            offset += STORAGE_LIST_PAGE
    return total, count, False


def section_storage_usage() -> list[str]:
    conf = _supabase_ready()
    if conf is None:
        return [f"{L_STORAGE}: 未設定"]
    base, key = conf
    total, count, truncated = _walk_storage(base, key)
    mb = total / (1024 * 1024)
    pct = total / STORAGE_FREE_LIMIT_BYTES * 100
    suffix = "（途中で打ち切り）" if truncated else ""
    return [f"{L_STORAGE}: {mb:.0f}MB / 1GB（{pct:.0f}%）{count}個{suffix}"]


# --------------------------------------------------------------------------- #
# 6. LINE の当月消費（送ってよいかの判断も兼ねる）
# --------------------------------------------------------------------------- #
def section_line_quota(token: str) -> tuple[list[str], int | None]:
    """(本文の行, 当月の消費通数) を返す。消費が取れなければ通数は None。"""
    if not token:
        return [f"{L_LINE}: 未設定"], None
    payload = _get_json(LINE_QUOTA_URL, {"Authorization": f"Bearer {token}"})
    used = payload.get("totalUsage") if isinstance(payload, dict) else None
    if isinstance(used, bool) or not isinstance(used, (int, float)):
        return [f"{L_LINE}: 消費数を読めない"], None
    used = int(used)
    remaining = LINE_FREE_MONTHLY - used
    mark = "⚠️" if used >= LINE_SKIP_AT else "✅"
    return [f"{L_LINE}: {mark} 当月{used}/{LINE_FREE_MONTHLY}通（残り{remaining}）"], used


# --------------------------------------------------------------------------- #
# 7. 期限の決まっているリスク（残り30日以内、および期限切れ）
# --------------------------------------------------------------------------- #
def section_deadlines(today: date) -> list[str]:
    """残り DEADLINE_WARN_DAYS 日以内のものだけ出す。

    期限を過ぎたものも出す（黙らせない）。docs/FAILURE_MAP.md がこの3件を
    「予告を受けたが期限までに何もしなかった型の再発候補」と呼んでいるのに、
    過ぎた瞬間に消える設計だと、その再発をこちらの手で作り込むことになる。
    """
    lines: list[str] = []
    for label, iso in DEADLINES:
        due = parse_ymd(iso)
        if due is None:
            continue
        days = (due - today).days
        if days > DEADLINE_WARN_DAYS:
            continue
        if days < 0:
            lines.append(f"{L_DEADLINE}: 🔴 {label}（{iso}・{-days}日超過）")
        else:
            lines.append(f"{L_DEADLINE}: ⚠️ {label}まで{days}日（{iso}）")
    return lines


# --------------------------------------------------------------------------- #
# 8. 監視の一時停止（scripts/monitor/quota_pause.py の解除日）
# --------------------------------------------------------------------------- #
def section_pause(today: date, raw: str) -> list[str]:
    """一時停止ゲートが有効なら警告を1行。平常時は何も出さない（毎日出す価値が無いため）。

    変数が未設定でも quota_pause.py はコード側の既定日で動くので、そのときは
    既定日で判定する（変数だけを見ると「効いているのに黙る」穴になる）。

    文面は「一時停止中」と言い切らない: quota_pause.py が実際に黙らせるのは
    **Supabase が 402 を返しているときだけ**で、日付は条件の片方に過ぎない。
    言い切ると「監視が死んでいる」と誤読され、逆に効いていないと誤読されるのも困る。
    """
    text = raw.strip()
    if not text:
        if not GATE_DEFAULT_UNTIL:
            return []
        until = parse_ymd(GATE_DEFAULT_UNTIL)
        if until is None or until <= today:
            return []
        return [f"{L_PAUSE}: ⚠️ ゲート有効（{until.isoformat()}まで・既定値）"]

    until = parse_ymd(text)
    if until is None:
        return [f"{L_PAUSE}: ⚠️ 解除日を日付として読めません（YYYY-MM-DD 形式で指定）"]
    if until > today:
        # quota_pause.py は today >= until で解除。つまり until より前が停止期間。
        return [f"{L_PAUSE}: ⚠️ ゲート有効（{until.isoformat()}まで・402のときだけ黙ります）"]
    return []


# --------------------------------------------------------------------------- #
# 組み立て
# --------------------------------------------------------------------------- #
def build_digest(*, now: datetime | None = None, dry_run: bool = False) -> Digest:
    """8項目を集めて1通ぶんの本文にする。**ここでは送らない**（送信判断は main）。"""
    moment = now or datetime.now(timezone.utc)
    today = today_jst(moment)
    repo = (os.environ.get("GITHUB_REPOSITORY") or "").strip()
    gh_token = (os.environ.get("GITHUB_TOKEN") or "").strip()
    line_token = (os.environ.get("LINE_CHANNEL_ACCESS_TOKEN") or "").strip()
    pause_raw = os.environ.get("OPS_QUOTA_PAUSE_UNTIL") or ""

    lines: list[str] = [
        f"【めぐりび 朝の点検】{today.isoformat()}({_WEEKDAY_JA[today.weekday()]})",
        # この1行だけは何があっても本文の先頭に置く（切り詰められない位置）。
        # 「鳴らないこと」に気づけるかどうかが、この仕組みの価値のほぼ全部なので。
        "※14:00 までに届かない日は、この通知自体の異常です。",
    ]

    lines += _safe(L_FAILED, lambda: section_failed_runs(repo, gh_token, moment))
    lines += _safe(L_STOPPED, lambda: section_workflow_states(repo, gh_token))
    lines += _safe(L_SITE, section_site_health)
    lines += _safe(L_COLLECT, lambda: section_collection_freshness(moment))
    lines += _safe(L_STORAGE, section_storage_usage)

    used: int | None = None
    if dry_run:
        # --dry-run では LINE に**一切アクセスしない**（消費数の照会も送信もしない）。
        # ローカルでの動作確認が、意図せず外部へ出ていかないようにするため。
        lines.append(f"{L_LINE}: --dry-run のため照会しません")
    else:
        try:
            quota_lines, used = section_line_quota(line_token)
        except Exception as exc:  # noqa: BLE001
            quota_lines, used = [_fail_line(L_LINE, exc)], None
        lines += quota_lines

    lines += _safe(L_DEADLINE, lambda: section_deadlines(today))
    lines += _safe(L_PAUSE, lambda: section_pause(today, pause_raw))

    blocked: str | None = None
    if used is not None and used >= LINE_SKIP_AT:
        blocked = (
            f"当月の LINE 消費が {used}/{LINE_FREE_MONTHLY} 通に達しているため送信しません"
            f"（{LINE_SKIP_AT}通以上で停止。残り枠は本当の障害通知のために空けています）"
        )
    return Digest(lines=lines, blocked_reason=blocked)


# --------------------------------------------------------------------------- #
# 送信
# --------------------------------------------------------------------------- #
def send_line_push(message: str, token: str, user_id: str) -> int | None:
    """LINE Push を1通。返り値は HTTP ステータス（取れなければ None）。

    本文だけを送る。失敗しても例外を投げない（送れなかったことはサマリに出す）。
    """
    body = json.dumps(
        {"to": user_id, "messages": [{"type": "text", "text": message}]}, ensure_ascii=False
    ).encode("utf-8")
    req = urllib.request.Request(
        LINE_PUSH_URL,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            status = getattr(resp, "status", None)
            return status if isinstance(status, int) else 200
    except Exception as exc:  # noqa: BLE001
        # HTTPError は .code を持つ（401=トークン失効, 429=枠切れ）。それ以外は None。
        code = getattr(exc, "code", None)
        return code if isinstance(code, int) else None


def main(argv: list[str] | None = None) -> int:
    _configure_stdout_utf8()
    parser = argparse.ArgumentParser(description="毎朝1通の運用ダイジェスト")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="組み立てて表示するだけ。LINE には一切アクセスしない（消費数の照会も送信もしない）。",
    )
    args = parser.parse_args(argv)

    if load_env is not None:
        try:
            load_env()
        except Exception:  # noqa: BLE001 - .env が無い/壊れていても続行する
            pass

    try:
        digest = build_digest(dry_run=args.dry_run)
    except Exception as exc:  # noqa: BLE001 - ここで落ちてもワークフローは赤くしない
        digest = Digest(lines=[f"{LOG_PREFIX} ダイジェストを組み立てられませんでした（{type(exc).__name__}）"])

    body = digest.body
    print(body)
    _append_env_file("GITHUB_STEP_SUMMARY", "## 朝の点検ダイジェスト\n\n```\n" + body + "\n```\n")

    token = (os.environ.get("LINE_CHANNEL_ACCESS_TOKEN") or "").strip()
    user_id = (os.environ.get("LINE_USER_ID") or "").strip()

    if args.dry_run:
        note = "--dry-run のため送信しませんでした。"
    elif not token or not user_id:
        # 2026-09-18 時点の実態がこれ。ここで exit 1 にすると「唯一の通知経路」である
        # 失敗メールを毎朝1通増やすことになるので、警告だけ出して緑で終える。
        print("::warning::LINE_CHANNEL_ACCESS_TOKEN または LINE_USER_ID が未設定です。送信をスキップしました。")
        note = "LINE 未設定のため送信していません（本文はこのサマリにのみ出しています）。"
    elif digest.blocked_reason:
        print(f"::warning::{digest.blocked_reason}")
        note = digest.blocked_reason
    else:
        status = send_line_push(clip_for_line(body), token, user_id)
        if status is not None and 200 <= status < 300:
            note = f"LINE 送信: HTTP {status}"
        else:
            shown = status if status is not None else "（応答なし）"
            print(f"::warning::LINE の送信に失敗しました（HTTP {shown}）。")
            note = f"LINE 送信に失敗: HTTP {shown}"

    print(f"{LOG_PREFIX} {note}")
    _append_env_file("GITHUB_STEP_SUMMARY", f"\n{note}\n")
    # 常に 0。ここを非ゼロにすると、メールを減らすための仕組みが自分でメールを増やす。
    return 0


if __name__ == "__main__":
    sys.exit(main())
