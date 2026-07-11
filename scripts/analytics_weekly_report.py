"""OWNER-ONLY weekly analytics digest for めぐりび (meguribi.jp).

何をするスクリプトか
--------------------
先週（月〜日, JST）と前週の GA4 / Search Console の数値を取得し、日本語の
週次ダイジェスト（LINE 向け・約2000字上限）を組み立てる。生の指標 JSON は
Supabase Storage の *private* バケット（`ml-models/analytics/weekly/<週初の月曜>.json`）へ
アップロードし、ダイジェスト本文は %TEMP% にローカル保存する。LINE の宛先
（`LINE_USER_ID`）が設定されていれば、既存の相席屋アラートと同じ Push 経路で
オーナーへ送信する。

公開リポジトリのため数値・鍵は一切コミットしない
------------------------------------------------
- サービスアカウント鍵は `secrets/ga-service-account.json`（.gitignore 済み）。
- 認証情報・数値は env / .env.local（.gitignore 済み）と private バケットのみ。
- **セットアップ未完了でも安全に no-op する**: 認証情報が無ければ日本語の案内
  （docs/ANALYTICS_SETUP.md を参照）を出して exit 0。GHA の `schedule:` ではなく
  オーナー PC の Task Scheduler（MEGRIBI-analytics-weekly）で毎週月曜 09:00 に回す前提。

使い方
------
    python scripts/analytics_weekly_report.py --dry-run   # 取得+組立+表示のみ（保存/送信なし）
    python scripts/analytics_weekly_report.py             # 取得+Supabase保存+ローカル保存+LINE送信

必要な環境変数（詳細は docs/ANALYTICS_SETUP.md）
    GA4_PROPERTY_ID            GA4 プロパティ ID（数字のみ）
    GA_SERVICE_ACCOUNT_JSON    サービスアカウント鍵のパス（既定: secrets/ga-service-account.json）
    GSC_SITE_URL              Search Console のプロパティ URL（既定: https://www.meguribi.jp/）
    SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY   生 JSON の保存先（private バケット）
    LINE_CHANNEL_ACCESS_TOKEN / LINE_USER_ID   ダイジェストの LINE 送信（任意）

依存: 標準ライブラリ + requests（既存依存）+ google-auth（新規・認証時のみ遅延 import）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

JST = timezone(timedelta(hours=9))

# 既定値（すべて env で上書き可能）。
DEFAULT_SA_PATH = REPO_ROOT / "secrets" / "ga-service-account.json"
# Search Console のプロパティ形式は「URL プレフィックス」。frontend/public/
# googlea5f06853b9c777a0.html（HTMLファイル方式の検証ファイル）が存在すること、
# および frontend/src/lib/siteUrl.ts の本番 canonical が https://www.meguribi.jp である
# ことから、登録済みプロパティは末尾スラッシュ付き URL プレフィックスと判断している。
DEFAULT_GSC_SITE_URL = "https://www.meguribi.jp/"
DEFAULT_BUCKET = "ml-models"

# Google API のスコープ（どちらも読み取り専用＝閲覧専用ロボット）。
GA4_SCOPE = "https://www.googleapis.com/auth/analytics.readonly"
GSC_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"

# ダイジェストの上限（LINE の 1 通は 5000 字だが、可読性のため 2000 字で切る）。
DIGEST_MAX_CHARS = 2000

# frontend 側で送っているカスタムイベント（frontend/src/lib/analytics.ts の sendEvent 呼び出し）。
# GA4 の eventCount by eventName から拾って表示する。GA4 自動収集イベント
# （page_view / session_start / first_visit / scroll ...）と区別するための参照リスト。
KNOWN_CUSTOM_EVENTS = ["store_view", "report_read", "favorite_add", "favorite_remove"]

FRIENDLY_SETUP_HINT = (
    "[analytics] 週次アナリティクスの認証情報が見つかりません（未セットアップ）。\n"
    "  このスクリプトは設定が完了するまで安全に何もしません（正常終了）。\n"
    "  有効化の手順は docs/ANALYTICS_SETUP.md を参照してください。\n"
    "  必要なもの: GA4_PROPERTY_ID（.env.local）と secrets/ga-service-account.json（鍵ファイル）。"
)


# --------------------------------------------------------------------------
# env 読み込み（snapshot_forecasts.py と同じ規約）
# --------------------------------------------------------------------------


def _load_env() -> None:
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


# --------------------------------------------------------------------------
# 週の窓計算（純粋関数・テスト対象）
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class WeekWindows:
    cur_start: date
    cur_end: date
    prev_start: date
    prev_end: date

    def as_dict(self) -> dict:
        return {
            "cur": {"start": self.cur_start.isoformat(), "end": self.cur_end.isoformat()},
            "prev": {"start": self.prev_start.isoformat(), "end": self.prev_end.isoformat()},
        }


def last_full_week(now_jst: datetime) -> WeekWindows:
    """直近で「完全に終わった」月〜日の週と、その前週を返す（すべて JST の日付）。

    月曜 09:00 に回す想定。例えば実行日が月曜なら、対象は前日（日曜）で終わる
    直前の月〜日。実行が週の途中でも、常に「今週の月曜より前の、完結した月〜日」。
    """
    today = now_jst.date()
    # 月曜=0 ... 日曜=6。今週の月曜まで巻き戻す。
    this_week_monday = today - timedelta(days=today.weekday())
    cur_end = this_week_monday - timedelta(days=1)   # 先週の日曜
    cur_start = cur_end - timedelta(days=6)          # 先週の月曜
    prev_end = cur_start - timedelta(days=1)          # 前週の日曜
    prev_start = prev_end - timedelta(days=6)         # 前週の月曜
    return WeekWindows(cur_start, cur_end, prev_start, prev_end)


# --------------------------------------------------------------------------
# 前週比の計算・整形（純粋関数・テスト対象）
# --------------------------------------------------------------------------


def wow_delta(cur, prev) -> tuple[float, float | None]:
    """(差分, 変化率%) を返す。前週が 0 のときは率を None（=算出不能）にする。"""
    c = float(cur or 0)
    p = float(prev or 0)
    delta = c - p
    pct = None if p == 0 else (delta / p * 100.0)
    return delta, pct


def fmt_int(n) -> str:
    return f"{int(round(float(n or 0))):,}"


def wow_str(cur, prev) -> str:
    """「+12.2% ↑」のような前週比の文字列。前週 0→今週>0 は「新規」。"""
    delta, pct = wow_delta(cur, prev)
    if pct is None:
        return "±0" if float(cur or 0) == 0 else "新規"
    arrow = "↑" if delta > 0 else ("↓" if delta < 0 else "→")
    sign = "+" if delta >= 0 else ""
    return f"{sign}{pct:.1f}% {arrow}"


def top_growth(cur_list, prev_list, key_field: str, value_field: str):
    """cur/prev のリストを突き合わせ、最も伸びた要素 (item, 差分) を返す。

    伸びが無ければ（全て横ばい/減少）、伸び最大（=減少最小）の要素を返す。
    リストが空なら None。
    """
    if not cur_list:
        return None
    prev_map = {row.get(key_field): float(row.get(value_field) or 0) for row in (prev_list or [])}
    best = None
    best_delta = None
    for row in cur_list:
        k = row.get(key_field)
        delta = float(row.get(value_field) or 0) - prev_map.get(k, 0.0)
        if best_delta is None or delta > best_delta:
            best_delta = delta
            best = row
    return (best, best_delta)


# --------------------------------------------------------------------------
# GA4 / GSC のリクエストボディ生成（純粋関数・テスト対象）
# --------------------------------------------------------------------------


def ga4_totals_body(start: str, end: str) -> dict:
    return {
        "dateRanges": [{"startDate": start, "endDate": end}],
        "metrics": [
            {"name": "activeUsers"},
            {"name": "sessions"},
            {"name": "screenPageViews"},
        ],
    }


def ga4_dim_body(start: str, end: str, dimension: str, metric: str, limit: int = 10) -> dict:
    return {
        "dateRanges": [{"startDate": start, "endDate": end}],
        "dimensions": [{"name": dimension}],
        "metrics": [{"name": metric}],
        "orderBys": [{"metric": {"metricName": metric}, "desc": True}],
        "limit": limit,
    }


def gsc_body(start: str, end: str, dimensions: list[str], row_limit: int = 10) -> dict:
    body: dict = {"startDate": start, "endDate": end, "rowLimit": row_limit}
    if dimensions:
        body["dimensions"] = dimensions
    return body


# --------------------------------------------------------------------------
# レスポンス parse（純粋関数・テスト対象）
# --------------------------------------------------------------------------


def parse_ga4_totals(resp: dict) -> dict:
    """runReport（次元なし）の 1 行目を metric 名→数値へ。行が無ければ 0。"""
    headers = [h.get("name") for h in (resp or {}).get("metricHeaders", [])]
    rows = (resp or {}).get("rows") or []
    out = {name: 0.0 for name in headers}
    if rows:
        values = rows[0].get("metricValues") or []
        for name, mv in zip(headers, values):
            out[name] = float(mv.get("value") or 0)
    return out


def parse_ga4_rows(resp: dict) -> list[tuple[str, float]]:
    """runReport（次元1つ・metric1つ）を [(dim値, metric値)] へ。"""
    out: list[tuple[str, float]] = []
    for row in (resp or {}).get("rows") or []:
        dims = row.get("dimensionValues") or []
        vals = row.get("metricValues") or []
        if not dims or not vals:
            continue
        out.append((dims[0].get("value") or "", float(vals[0].get("value") or 0)))
    return out


def parse_gsc_totals(resp: dict) -> dict:
    rows = (resp or {}).get("rows") or []
    if not rows:
        return {"clicks": 0.0, "impressions": 0.0, "ctr": 0.0, "position": 0.0}
    r = rows[0]
    return {
        "clicks": float(r.get("clicks") or 0),
        "impressions": float(r.get("impressions") or 0),
        "ctr": float(r.get("ctr") or 0),
        "position": float(r.get("position") or 0),
    }


def parse_gsc_rows(resp: dict) -> list[dict]:
    out: list[dict] = []
    for r in (resp or {}).get("rows") or []:
        keys = r.get("keys") or []
        out.append(
            {
                "key": keys[0] if keys else "",
                "clicks": float(r.get("clicks") or 0),
                "impressions": float(r.get("impressions") or 0),
                "ctr": float(r.get("ctr") or 0),
                "position": float(r.get("position") or 0),
            }
        )
    return out


# --------------------------------------------------------------------------
# 指標の取得（ネットワーク境界は ga4_call / gsc_call に注入 → テストは fake を渡す）
# --------------------------------------------------------------------------


def fetch_metrics(weeks: WeekWindows, ga4_call, gsc_call) -> dict:
    """GA4 / GSC を叩いて metrics dict を組む。個々の失敗は握りつぶし warnings に残す
    （1 種類のクエリが落ちても他は出す）。ga4_call(body)->resp, gsc_call(body)->resp。"""
    warnings: list[str] = []

    def safe(fn, *args, default=None, label=""):
        try:
            return fn(*args)
        except Exception as exc:  # noqa: BLE001 - best-effort, digest は部分データでも成立させる
            warnings.append(f"{label}: {str(exc)[:120]}")
            return default

    cs, ce = weeks.cur_start.isoformat(), weeks.cur_end.isoformat()
    ps, pe = weeks.prev_start.isoformat(), weeks.prev_end.isoformat()

    # ---- GA4 ----
    ga4_totals_cur = parse_ga4_totals(safe(ga4_call, ga4_totals_body(cs, ce), default={}, label="ga4.totals.cur"))
    ga4_totals_prev = parse_ga4_totals(safe(ga4_call, ga4_totals_body(ps, pe), default={}, label="ga4.totals.prev"))

    top_pages_cur = [
        {"path": k, "views": v}
        for k, v in parse_ga4_rows(
            safe(ga4_call, ga4_dim_body(cs, ce, "pagePath", "screenPageViews", 10), default={}, label="ga4.pages.cur")
        )
    ]
    top_pages_prev = [
        {"path": k, "views": v}
        for k, v in parse_ga4_rows(
            safe(ga4_call, ga4_dim_body(ps, pe, "pagePath", "screenPageViews", 10), default={}, label="ga4.pages.prev")
        )
    ]

    events_cur = dict(
        parse_ga4_rows(
            safe(ga4_call, ga4_dim_body(cs, ce, "eventName", "eventCount", 25), default={}, label="ga4.events.cur")
        )
    )
    events_prev = dict(
        parse_ga4_rows(
            safe(ga4_call, ga4_dim_body(ps, pe, "eventName", "eventCount", 25), default={}, label="ga4.events.prev")
        )
    )

    channels_cur = [
        {"channel": k, "sessions": v}
        for k, v in parse_ga4_rows(
            safe(
                ga4_call,
                ga4_dim_body(cs, ce, "sessionDefaultChannelGroup", "sessions", 10),
                default={},
                label="ga4.channels.cur",
            )
        )
    ]

    # ---- GSC ----
    gsc_totals_cur = parse_gsc_totals(safe(gsc_call, gsc_body(cs, ce, [], 1), default={}, label="gsc.totals.cur"))
    gsc_totals_prev = parse_gsc_totals(safe(gsc_call, gsc_body(ps, pe, [], 1), default={}, label="gsc.totals.prev"))

    gsc_queries_cur = [
        {"query": r["key"], "clicks": r["clicks"], "impressions": r["impressions"]}
        for r in parse_gsc_rows(safe(gsc_call, gsc_body(cs, ce, ["query"], 10), default={}, label="gsc.queries.cur"))
    ]
    gsc_queries_prev = [
        {"query": r["key"], "clicks": r["clicks"], "impressions": r["impressions"]}
        for r in parse_gsc_rows(safe(gsc_call, gsc_body(ps, pe, ["query"], 10), default={}, label="gsc.queries.prev"))
    ]
    gsc_pages_cur = [
        {"page": r["key"], "clicks": r["clicks"], "impressions": r["impressions"]}
        for r in parse_gsc_rows(safe(gsc_call, gsc_body(cs, ce, ["page"], 10), default={}, label="gsc.pages.cur"))
    ]

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "weeks": weeks.as_dict(),
        "ga4": {
            "totals": {"cur": ga4_totals_cur, "prev": ga4_totals_prev},
            "top_pages": {"cur": top_pages_cur, "prev": top_pages_prev},
            "events": {"cur": events_cur, "prev": events_prev},
            "channels": {"cur": channels_cur},
        },
        "gsc": {
            "totals": {"cur": gsc_totals_cur, "prev": gsc_totals_prev},
            "top_queries": {"cur": gsc_queries_cur, "prev": gsc_queries_prev},
            "top_pages": {"cur": gsc_pages_cur},
        },
        "warnings": warnings,
    }


# --------------------------------------------------------------------------
# ダイジェスト組み立て（純粋関数・テスト対象）
# --------------------------------------------------------------------------


def compose_digest(metrics: dict) -> str:
    weeks = metrics.get("weeks", {})
    cur_w = weeks.get("cur", {})
    prev_w = weeks.get("prev", {})
    ga4 = metrics.get("ga4", {})
    gsc = metrics.get("gsc", {})

    lines: list[str] = []
    lines.append("【めぐりび 週次アナリティクス】")
    lines.append(f"対象: {cur_w.get('start', '?')}〜{cur_w.get('end', '?')}")
    lines.append(f"（前週比: {prev_w.get('start', '?')}〜{prev_w.get('end', '?')}）")
    lines.append("")

    # --- GA4 サイト全体 ---
    gt = ga4.get("totals", {})
    gc = gt.get("cur", {})
    gp = gt.get("prev", {})
    lines.append("■ サイト全体（GA4）")
    lines.append(
        f"・アクティブユーザー: {fmt_int(gc.get('activeUsers'))}"
        f"（前週比 {wow_str(gc.get('activeUsers'), gp.get('activeUsers'))}）"
    )
    lines.append(
        f"・セッション: {fmt_int(gc.get('sessions'))}"
        f"（前週比 {wow_str(gc.get('sessions'), gp.get('sessions'))}）"
    )
    lines.append(
        f"・ページビュー: {fmt_int(gc.get('screenPageViews'))}"
        f"（前週比 {wow_str(gc.get('screenPageViews'), gp.get('screenPageViews'))}）"
    )
    lines.append("")

    # --- Search Console ---
    st = gsc.get("totals", {})
    sc = st.get("cur", {})
    sp = st.get("prev", {})
    lines.append("■ 検索流入（Search Console）")
    lines.append(f"・クリック: {fmt_int(sc.get('clicks'))}（前週比 {wow_str(sc.get('clicks'), sp.get('clicks'))}）")
    lines.append(
        f"・表示回数: {fmt_int(sc.get('impressions'))}"
        f"（前週比 {wow_str(sc.get('impressions'), sp.get('impressions'))}）"
    )
    cur_ctr = float(sc.get("ctr") or 0) * 100.0
    prev_ctr = float(sp.get("ctr") or 0) * 100.0
    lines.append(f"・平均CTR: {cur_ctr:.2f}%（前週 {prev_ctr:.2f}%）")
    lines.append(f"・平均掲載順位: {float(sc.get('position') or 0):.1f}位（前週 {float(sp.get('position') or 0):.1f}位）")
    lines.append("")

    # --- 今週のハイライト ---
    lines.append("■ 今週のハイライト")
    pg = top_growth(ga4.get("top_pages", {}).get("cur"), ga4.get("top_pages", {}).get("prev"), "path", "views")
    if pg and pg[0]:
        item, delta = pg
        sign = "+" if delta >= 0 else ""
        lines.append(f"・最も伸びたページ: {item.get('path')}（{sign}{fmt_int(delta)}PV）")
    qg = top_growth(
        gsc.get("top_queries", {}).get("cur"), gsc.get("top_queries", {}).get("prev"), "query", "clicks"
    )
    if qg and qg[0]:
        item, delta = qg
        sign = "+" if delta >= 0 else ""
        lines.append(f"・最も伸びた検索クエリ: 「{item.get('query')}」（{sign}{fmt_int(delta)}クリック）")
    if not (pg and pg[0]) and not (qg and qg[0]):
        lines.append("・（比較可能なデータがまだありません）")
    lines.append("")

    # --- 人気ページ TOP5 ---
    top_pages = (ga4.get("top_pages", {}).get("cur") or [])[:5]
    if top_pages:
        lines.append("■ 人気ページ TOP5（PV）")
        for i, row in enumerate(top_pages, 1):
            lines.append(f"{i}. {row.get('path')} … {fmt_int(row.get('views'))}")
        lines.append("")

    # --- 流入チャネル ---
    channels = (ga4.get("channels", {}).get("cur") or [])[:5]
    if channels:
        lines.append("■ 流入チャネル（セッション）")
        for row in channels:
            lines.append(f"・{row.get('channel')}: {fmt_int(row.get('sessions'))}")
        lines.append("")

    # --- カスタムイベント利用状況 ---
    events_cur = ga4.get("events", {}).get("cur", {}) or {}
    events_prev = ga4.get("events", {}).get("prev", {}) or {}
    shown = [(name, events_cur[name]) for name in KNOWN_CUSTOM_EVENTS if name in events_cur]
    if shown:
        lines.append("■ イベント利用状況（サイト内アクション）")
        for name, cnt in shown:
            lines.append(f"・{name}: {fmt_int(cnt)}（前週比 {wow_str(cnt, events_prev.get(name))}）")
        lines.append("")

    # --- 注記 ---
    if metrics.get("warnings"):
        lines.append("※ 一部データの取得に失敗しました（詳細はログを参照）。")
    lines.append("※ Search Console の直近2日は集計途中の場合があります。")
    lines.append("※ 本レポートは非公開（数値は private バケットに保存）。")

    text = "\n".join(lines)
    if len(text) > DIGEST_MAX_CHARS:
        text = text[: DIGEST_MAX_CHARS - 8].rstrip() + "\n…（省略）"
    return text


# --------------------------------------------------------------------------
# 認証（google-auth は遅延 import ＝ 未インストールでも --dry-run/no-cred は動く）
# --------------------------------------------------------------------------


def google_access_token(sa_path: Path, scopes: list[str]) -> str | None:
    """サービスアカウント鍵からアクセストークンを発行。google-auth 未導入なら None。"""
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request as GoogleAuthRequest
    except ImportError:
        return None
    creds = service_account.Credentials.from_service_account_file(str(sa_path), scopes=scopes)
    creds.refresh(GoogleAuthRequest())
    return creds.token


def _ga4_run_report(token: str, property_id: str, body: dict) -> dict:
    import requests

    url = f"https://analyticsdata.googleapis.com/v1beta/properties/{property_id}:runReport"
    resp = requests.post(url, json=body, headers={"Authorization": f"Bearer {token}"}, timeout=60)
    resp.raise_for_status()
    return resp.json()


def _gsc_query(token: str, site_url: str, body: dict) -> dict:
    import requests

    encoded = urllib.parse.quote(site_url, safe="")
    url = f"https://searchconsole.googleapis.com/webmasters/v3/sites/{encoded}/searchAnalytics/query"
    resp = requests.post(url, json=body, headers={"Authorization": f"Bearer {token}"}, timeout=60)
    resp.raise_for_status()
    return resp.json()


# --------------------------------------------------------------------------
# 永続化（Supabase Storage：snapshot_forecasts.py の put 規約を踏襲）
# --------------------------------------------------------------------------


def _storage_put(bucket: str, path: str, payload: bytes, url: str, key: str) -> None:
    endpoint = f"{url}/storage/v1/object/{bucket}/{path}"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "x-upsert": "true",
        "Content-Type": "application/json",
    }
    req = urllib.request.Request(endpoint, data=payload, method="POST", headers=headers)
    urllib.request.urlopen(req, timeout=30)


def upload_metrics(metrics: dict, weeks: WeekWindows) -> str | None:
    """生 JSON を private バケットへ。SUPABASE 未設定なら None（警告のみ、失敗にしない）。"""
    supabase_url = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_SERVICE_KEY") or ""
    bucket = (os.environ.get("FORECAST_MODEL_BUCKET") or DEFAULT_BUCKET).strip()
    if not supabase_url or not key:
        print("[analytics] SUPABASE 未設定のため生JSONの保存をスキップしました。")
        return None
    path = f"analytics/weekly/{weeks.cur_start.isoformat()}.json"
    _storage_put(bucket, path, json.dumps(metrics, ensure_ascii=False).encode("utf-8"), supabase_url, key)
    dest = f"{bucket}/{path}"
    print(f"[analytics] 生JSONを保存しました -> {dest}")
    return dest


def write_local_log(digest: str, weeks: WeekWindows) -> Path:
    log_dir = Path(os.environ.get("ANALYTICS_LOG_DIR") or tempfile.gettempdir())
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"analytics_weekly_{weeks.cur_start.isoformat()}.txt"
    log_path.write_text(digest + "\n", encoding="utf-8")
    return log_path


# --------------------------------------------------------------------------
# LINE 配信（multi_collect.py::_send_line_push と同じ Push 経路・同じ env）
# --------------------------------------------------------------------------


def send_line_push(message: str) -> bool:
    """LINE Push でオーナーへ送信。宛先(LINE_USER_ID)/トークン未設定なら False（=未配線）。"""
    token = (os.environ.get("LINE_CHANNEL_ACCESS_TOKEN") or "").strip()
    user_id = (os.environ.get("LINE_USER_ID") or "").strip()
    if not token or not user_id:
        return False
    import requests

    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
    body = {"to": user_id, "messages": [{"type": "text", "text": message}]}
    try:
        resp = requests.post(url, json=body, headers=headers, timeout=10)
        print(f"[analytics] LINE push status={resp.status_code} body={resp.text[:200]}")
        return 200 <= resp.status_code < 300
    except Exception as exc:  # noqa: BLE001
        print(f"[analytics][error] LINE push failed: {exc}")
        return False


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def _configure_stdout_utf8() -> None:
    # Windows の既定コンソール(cp932)で日本語を print すると UnicodeEncodeError に
    # なり得る（CLAUDE.md 罠#9）。utf-8 + replace で握って Task Scheduler 実行でも落とさない。
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            pass


def _credentials_present(property_id: str, sa_path: Path) -> bool:
    return bool(property_id) and sa_path.is_file()


def main(argv: list[str] | None = None) -> int:
    _configure_stdout_utf8()
    ap = argparse.ArgumentParser(description="めぐりび 週次アナリティクス・ダイジェスト（オーナー専用）")
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="取得と組み立てだけ行い、標準出力に表示する（Supabase保存もLINE送信もしない）。",
    )
    args = ap.parse_args(argv)

    _load_env()

    property_id = (os.environ.get("GA4_PROPERTY_ID") or "").strip()
    sa_path = Path(
        os.environ.get("GA_SERVICE_ACCOUNT_JSON")
        or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        or DEFAULT_SA_PATH
    )
    site_url = (os.environ.get("GSC_SITE_URL") or DEFAULT_GSC_SITE_URL).strip()

    # 認証情報が無ければ「安全に何もしない」（案内を出して正常終了）。
    if not _credentials_present(property_id, sa_path):
        print(FRIENDLY_SETUP_HINT)
        return 0

    token = google_access_token(sa_path, [GA4_SCOPE, GSC_SCOPE])
    if token is None:
        print(
            "[analytics] google-auth が未インストールのため認証できません。\n"
            "  `pip install -r requirements.txt` を実行してから再度お試しください。\n"
            "  （手順は docs/ANALYTICS_SETUP.md を参照）"
        )
        return 0

    now_jst = datetime.now(JST)
    weeks = last_full_week(now_jst)
    print(
        f"[analytics] 対象週 {weeks.cur_start}〜{weeks.cur_end}"
        f"（前週 {weeks.prev_start}〜{weeks.prev_end}）を集計します。"
    )

    def ga4_call(body: dict) -> dict:
        return _ga4_run_report(token, property_id, body)

    def gsc_call(body: dict) -> dict:
        return _gsc_query(token, site_url, body)

    metrics = fetch_metrics(weeks, ga4_call, gsc_call)
    digest = compose_digest(metrics)

    if args.dry_run:
        print("\n===== DRY RUN: 生成したダイジェスト =====\n")
        print(digest)
        if metrics.get("warnings"):
            print("\n[warn] " + " / ".join(metrics["warnings"]))
        return 0

    # 生 JSON を private バケットへ、ダイジェストをローカルへ。
    upload_metrics(metrics, weeks)
    log_path = write_local_log(digest, weeks)

    # LINE 送信（未配線でも失敗にしない）。
    if send_line_push(digest):
        print(f"[analytics] LINE でダイジェストを送信しました。ローカル控え: {log_path}")
    else:
        print(f"[analytics] LINE未配線（LINE_USER_ID 未設定）— digestは {log_path} に保存しました。")

    if metrics.get("warnings"):
        print("[warn] " + " / ".join(metrics["warnings"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
