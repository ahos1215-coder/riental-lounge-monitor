"""OWNER-ONLY weekly analytics digest for めぐりび (meguribi.jp).

何をするスクリプトか
--------------------
先週（月〜日, JST）と前週の GA4 / Search Console の数値を取得し、日本語の
週次ダイジェスト（LINE 向け・約2000字上限）を組み立てる。生の指標 JSON は
Supabase Storage（`ml-models/analytics/weekly/<週初の月曜>.json`）へアップロードし、
ダイジェスト本文は %TEMP% にローカル保存する。LINE の宛先
（`LINE_USER_ID`）が設定されていれば、既存の相席屋アラートと同じ Push 経路で
オーナーへ送信する。

公開リポジトリのため数値・鍵は一切コミットしない
------------------------------------------------
- サービスアカウント鍵は `secrets/ga-service-account.json`（.gitignore 済み）。
- 認証情報・数値は env / .env.local（.gitignore 済み）と Supabase Storage のみ。
  ⚠️ 2026-09-06 訂正: `ml-models` バケットは実測で**匿名 GET に 200 を返す＝公開設定**。
  「private バケットだから安全」と書いていたのは事実誤りだった。URL を知る第三者は保存済みの
  生 JSON を読めるため、`bucket_appears_public()` で公開を検知したときは検索語を伏字にして
  アップロードする（fail-closed）。private 化の手順は docs/ANALYTICS_SETUP.md §9。
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
    SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY   生 JSON の保存先（Storage バケット。
                               2026-09-06 時点で公開設定＝匿名 GET 可。docs/ANALYTICS_SETUP.md §9 参照）
    LINE_CHANNEL_ACCESS_TOKEN / LINE_USER_ID   ダイジェストの LINE 送信（任意）

依存: 標準ライブラリ + requests（既存依存）+ google-auth（新規・認証時のみ遅延 import）。
"""

from __future__ import annotations

import argparse
import functools
import json
import math
import os
import re
import sys
import tempfile
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# scripts/_supabase_common.py（.env 読み込み・Storage PUT の共有実装、stdlib のみ）を
# シブリングとしてベアインポートする。
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _supabase_common import _load_env, _supabase_conf, storage_put  # noqa: E402

# ログ接頭辞だけを固定した別名（モジュール変数名は従来どおり `_storage_put`）。
_storage_put = functools.partial(storage_put, log_prefix="[analytics]")

JST = timezone(timedelta(hours=9))

# 2026-08-26 に手動PVの発火条件（searchParams変更を手動PVから除外・?store=自動付与の削除等）を
# 変更した。この日より前のPV(screenPageViews)には旧ロジックの水増しが混じるため、この日を
# またぐ前期間比は意味を持たない（計測レビューR2 修正6）。他の指標（activeUsers/sessions/GSC等）
# には適用しない — PVという値の定義そのものが変わったことへの対処であり、確定/未確定の話とは別。
PV_DEFINITION_CHANGE_AT = date(2026, 8, 26)

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

# frontend 側で送っているカスタムイベント（frontend/src/lib/analytics.ts の track/sendEvent 呼び出し）。
# GA4 の eventCount by eventName から拾って表示する。GA4 自動収集イベント
# （page_view / session_start / first_visit / scroll ...）と区別するための参照リスト。
#
# 2026-08-26 計測レビュー対応（第2ラウンド）: このリストは
# frontend/src/lib/analytics.ts::ANALYTICS_EVENT_NAMES（TS側SSOT・12種）と一字一句一致させる
# こと。ここは12種 + report_read（report_view への改名前の互換名。旧データの前週比較のため
# 残す）の合計13種。TS/Python の乖離は tests/test_analytics_event_parity.py が固定する
# （TS配列を正規表現で読み取り、この一覧 - {"report_read"} と集合一致を検証）。
# report_view と report_read は表示時に合算する（canonical_events_for_display / 修正6）。
KNOWN_CUSTOM_EVENTS = [
    "store_view",
    "report_view",
    "favorite_add",
    "favorite_remove",
    "compare_add_store",
    "range_mode_change",
    "cost_sim_interact",
    "related_store_click",
    "official_site_click",
    "second_venue_click",
    "official_site_view",
    "second_venue_view",
    "report_read",
]

# 閉店済み店舗の slug（frontend/src/proxy.ts::CLOSED_STORE_SLUGS と同じ集合。あちらが
# リダイレクト判定の正本で、ここは検索流入レポートのページ分類用に写した小さな複製。
# 閉店店舗が増えたら両方を直すこと）。
CLOSED_STORE_SLUGS = frozenset({"ay_niigata", "sapporo_ag"})

# 「有効検索クリック」の対象カテゴリ（非noindexの一覧・詳細ページ群）。
# report は noindex（frontend/src/app/reports/daily・weekly/[store_slug]/page.tsx）なので対象外。
QUALIFIED_PAGE_CATEGORIES = frozenset({"home", "store", "area", "stores", "blog"})

FRIENDLY_SETUP_HINT = (
    "[analytics] 週次アナリティクスの認証情報が見つかりません（未セットアップ）。\n"
    "  このスクリプトは設定が完了するまで安全に何もしません（正常終了）。\n"
    "  有効化の手順は docs/ANALYTICS_SETUP.md を参照してください。\n"
    "  必要なもの: GA4_PROPERTY_ID（.env.local）と secrets/ga-service-account.json（鍵ファイル）。"
)


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


def pv_epoch(d: date) -> str:
    """指定日が PV_DEFINITION_CHANGE_AT を境にどちらのepochかを返す（計測レビューR2 修正6）。"""
    return "new" if d >= PV_DEFINITION_CHANGE_AT else "old"


def pv_delta_crosses_boundary(cur_start: date, cur_end: date, prev_start: date, prev_end: date) -> bool:
    """前期間比較に使う4つの日付が PV_DEFINITION_CHANGE_AT をまたぐか。

    またぐ場合、PV(screenPageViews)の前期間比は新旧の計測ロジックが混じり比較不能になる
    （計測レビューR2 修正6）。activeUsers/sessions/GSC指標には適用しない。
    """
    epochs = {pv_epoch(cur_start), pv_epoch(cur_end), pv_epoch(prev_start), pv_epoch(prev_end)}
    return len(epochs) > 1


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


def last_confirmed_week(now_jst: datetime, min_lag_days: int = 3) -> WeekWindows:
    """GSC 用：「完全に確定した」直近の月〜日週を返す（前週比の相方も同じだけ遡る）。

    2026-08-26 計測レビュー対応（修正1d）: GSC は月曜朝実行だと直前の日曜まで含む週の
    データがまだ確定しておらず、実測で 8/24 時点228件→8/26確定328件と大きくブレることを
    確認済み（「未確定週問題」）。`last_full_week()` が返す週の終端（日曜）から実行日までの
    日数が `min_lag_days` 未満なら、確定するまで週単位でまるごと1週遡る。月曜09:00実行なら
    直近完結週（日曜終端、実行日との差1日）はまだ足りず、1週遡った前々週（差8日）で確定と
    判定する。cur/prev を同じ週数だけ遡らせるので、前週比も常に「確定週同士」の比較になる。
    """
    w = last_full_week(now_jst)
    today = now_jst.date()
    while (today - w.cur_end).days < min_lag_days:
        w = WeekWindows(
            cur_start=w.cur_start - timedelta(days=7),
            cur_end=w.cur_end - timedelta(days=7),
            prev_start=w.prev_start - timedelta(days=7),
            prev_end=w.prev_end - timedelta(days=7),
        )
    return w


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


def fmt_metric_or_na(value, failed: bool) -> str:
    """取得に失敗した指標は "0" ではなく "取得失敗" と表示する（修正1c）。"""
    return "取得失敗" if failed else fmt_int(value)


def wow_str_or_na(cur, prev, cur_failed: bool, prev_failed: bool) -> str:
    """前週比版。cur/prev のどちらかが取得失敗なら、誤った%を出さず "取得失敗" にする（修正1c）。"""
    if cur_failed or prev_failed:
        return "取得失敗"
    return wow_str(cur, prev)


def format_md(iso_date: str) -> str:
    """ISO 日付文字列 "YYYY-MM-DD" を "M/D" 表記へ（先頭ゼロなし）。"""
    d = date.fromisoformat(iso_date)
    return f"{d.month}/{d.day}"


def top_growth(cur_list, prev_list, key_field: str, value_field: str):
    """cur/prev のリストを突き合わせ、最も伸びた要素 (item, 差分) を返す。

    2026-08-26 計測レビュー対応（修正1b）: 以前は伸びが無く全て横ばい/減少のときも
    「伸び最大（＝減少最小）」の要素を +0 や負の値のまま返しており、ダイジェストに
    「最も伸びたクエリ: 〜（+0クリック）」という誤解を招く行が実データで出ていた
    （実質「伸びていない」のに「伸びた」と表示していた）。差分が正のものが1つも無ければ
    None を返し、呼び出し側（compose_digest）はその行自体を出さない。
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
    if best_delta is None or best_delta <= 0:
        return None
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


def gsc_body(
    start: str, end: str, dimensions: list[str], row_limit: int = 10, data_state: str | None = None
) -> dict:
    body: dict = {"startDate": start, "endDate": end, "rowLimit": row_limit}
    if dimensions:
        body["dimensions"] = dimensions
    # data_state 省略時は GSC 側の既定 "final"（＝確定データのみ）になる（確認済み）。
    # analytics_report.py（最新分析CLI）は直近日も見たいので "all" を明示的に渡す。
    if data_state:
        body["dataState"] = data_state
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


def parse_gsc_query_page_rows(resp: dict) -> list[dict]:
    """dimensions=["query","page"] のレスポンスを [{query, page, clicks, ...}] へ。

    2026-08-26 計測レビュー対応（修正2）。keys の並びは dimensions の指定順（query→page）
    に対応する GSC API の仕様どおり。
    """
    out: list[dict] = []
    for r in (resp or {}).get("rows") or []:
        keys = r.get("keys") or []
        out.append(
            {
                "query": keys[0] if len(keys) > 0 else "",
                "page": keys[1] if len(keys) > 1 else "",
                "clicks": float(r.get("clicks") or 0),
                "impressions": float(r.get("impressions") or 0),
                "ctr": float(r.get("ctr") or 0),
                "position": float(r.get("position") or 0),
            }
        )
    return out


# --------------------------------------------------------------------------
# ページ分類・指名判定・順位帯・有効検索クリック（純粋関数・テスト対象）
# 2026-08-26 計測レビュー対応（修正2）。scripts/analytics_report.py（最新分析CLI）とも共有する。
# --------------------------------------------------------------------------


def classify_page_path(page_or_url: str) -> str:
    """URL またはパスを home/store/area/stores/blog/compare/reports_hub/report/closed/other に分類する。

    GSC の "page" ディメンションはフル URL（https://www.meguribi.jp/...）で返るが、
    パスだけの文字列を渡しても urlparse はそのまま path として扱うので同じ関数で両方さばける。
    閉店店舗（CLOSED_STORE_SLUGS）の /store/<slug> は「store」ではなく「closed」に分ける
    （検索結果に残っている閉店ページのクリックを、現役店舗の実績と混ぜないため）。

    2026-08-26 計測レビュー対応（第2ラウンド・修正5）: 以前は "/reports"（ハブ・indexable）と
    "/reports/daily|weekly/<slug>"（noindex詳細）を同じ "report" に混ぜ、"/compare" は
    「その他」扱いだった。ハブとdetail、compareを分離する。
    """
    path = urllib.parse.urlparse(page_or_url or "").path
    segments = [s for s in path.split("/") if s]
    if not segments:
        return "home"
    head = segments[0].lower()
    if head == "store" and len(segments) >= 2:
        slug = urllib.parse.unquote(segments[1]).lower()
        return "closed" if slug in CLOSED_STORE_SLUGS else "store"
    if head == "area":
        return "area"
    if head == "stores":
        return "stores"
    if head == "blog":
        return "blog"
    if head == "compare":
        return "compare"
    if head == "reports":
        return "reports_hub" if len(segments) == 1 else "report"
    return "other"


# チェーン（業態ブランド）名の指名判定に使う定数リスト。2026-08-26 計測レビュー対応（修正5）:
# frontend/src/data/stores.json（店舗マスタ）は読まない — ここで見たいのは店舗個別の来店意図
# ではなく「業態ブランド名そのもの」への検索意図（一般語との切り分け）なので、店舗一覧との
# 結合は不要。語彙は実データで確認できた表記ゆれのみ（過剰な誤字辞書は作らない）。
# 正規化（_normalize_query）後の比較のため、ここも小文字/全角スペース等のゆれは気にせず書ける。
CHAIN_BRAND_TERMS = (
    "オリエンタルラウンジ",
    "オリエンタル ラウンジ",
    "oriental lounge",
    "相席屋",
    "aisekiya",
)


def _normalize_query(q: str) -> str:
    """NFKC正規化 + casefold + 空白/ハイフン類の正規化。全角/半角・大文字小文字の表記ゆれを吸収する
    （2026-08-26 計測レビュー対応・修正5。実測に無い大量の誤字辞書は作らず、この範囲に留める）。
    """
    n = unicodedata.normalize("NFKC", q or "")
    n = n.casefold()
    n = re.sub(r"[\s\-‐-―ー]+", " ", n).strip()
    return n


def classify_query_brand(query: str) -> str:
    """検索語を site（サイト名指名）/ chain（チェーン業態名指名）/ generic（一般語）へ三分する。

    2026-08-26 計測レビュー対応（第2ラウンド・修正5）: 従来の is_branded_query はサイト名だけを
    「指名」とし、「オリエンタルラウンジ」「相席屋」等のチェーン名を含むナビゲーショナル検索を
    「一般」に混ぜていた。それだと generic SEO の実力を過大評価するため三分する。
    """
    q = _normalize_query(query)
    if "めぐりび" in q or "meguribi" in q or "megribi" in q:
        return "site"
    for term in CHAIN_BRAND_TERMS:
        if _normalize_query(term) in q:
            return "chain"
    return "generic"


def is_branded_query(query: str) -> bool:
    """検索語に指名（サイト名）が含まれるか。classify_query_brand の site 判定のラッパー
    （既存呼び出しとの後方互換のため維持）。

    表記ゆれ: 「めぐりび」/ ドメインの "meguribi"(.jp) / ブランド表記の "megribi"(MEGRIBI)。
    実データで「megribi」という検索が一般扱いになっていたのを 2026-08-26 の実CLI smoke で発見し追加。
    """
    return classify_query_brand(query) == "site"


def position_bucket(position) -> str:
    """GSC の平均掲載順位を 1-3 / 4-10 / 11-20 / 21+ / unknown の順位帯へ丸める。

    2026-08-26 計測レビュー対応（第2ラウンド・修正5）: 欠損(None)・0・非有限(NaN/Inf)は、
    以前は "1-3" に落ちてしまっていた（`float(position or 0)` が 0 を経由するため）。
    実際に掲載順位が測れていない行を「1〜3位」という良い順位に誤分類しないよう "unknown" にする。
    """
    if position is None:
        return "unknown"
    try:
        p = float(position)
    except (TypeError, ValueError):
        return "unknown"
    if not math.isfinite(p) or p <= 0:
        return "unknown"
    if p <= 3:
        return "1-3"
    if p <= 10:
        return "4-10"
    if p <= 20:
        return "11-20"
    return "21+"


def qualified_clicks_total(page_rows: list[dict], page_field: str = "page") -> tuple[float, float]:
    """(有効クリック, 全クリック) を返す。有効 = QUALIFIED_PAGE_CATEGORIES に分類されるページへのクリック。

    page_rows は {page_field: URL/パス, "clicks": 数値} を持つ行のリスト（GSC の page ディメンション
    行を想定）。report（noindex）・closed（閉店）・other（mypage 等）は対象外。
    """
    total = 0.0
    qualified = 0.0
    for row in page_rows or []:
        clicks = float(row.get("clicks") or 0)
        total += clicks
        if classify_page_path(row.get(page_field) or "") in QUALIFIED_PAGE_CATEGORIES:
            qualified += clicks
    return qualified, total


def compute_source_status(failed_labels: list[str], prefix: str, got_anything: bool) -> str:
    """ソース単位の取得状態を ok/partial/failed の3値へ要約する（2026-08-26 計測レビュー対応・
    修正5。metadata.source_status で使う）。`prefix` 始まりの失敗が1つも無ければ ok。失敗が
    あっても他のクエリで何か取れていれば partial、何も取れていなければ failed。
    analytics_report.py（最新分析CLI）とロジックを共有し、実装が2箇所でズレないようにする。
    """
    source_failed = [label for label in failed_labels if label.startswith(prefix)]
    if not source_failed:
        return "ok"
    return "partial" if got_anything else "failed"


def canonical_events_for_display(events: dict) -> dict:
    """表示専用: 旧名 report_read を report_view へ合算したコピーを返す（2026-08-26 計測レビュー
    対応・修正6）。改名直後は旧実績を前週値として使えず report_view が偽の「新規」に見えるため、
    表示・比較のときだけ canonicalize する。生の events dict（JSON出力側）は変更しない。
    """
    out = dict(events or {})
    if "report_read" in out:
        legacy = out.pop("report_read")
        out["report_view"] = out.get("report_view", 0) + legacy
    return out


# --------------------------------------------------------------------------
# 指標の取得（ネットワーク境界は ga4_call / gsc_call に注入 → テストは fake を渡す）
# --------------------------------------------------------------------------


def fetch_metrics(ga4_weeks: WeekWindows, gsc_weeks: WeekWindows, ga4_call, gsc_call) -> dict:
    """GA4 / GSC を叩いて metrics dict を組む。個々の失敗は握りつぶし warnings に残す
    （1 種類のクエリが落ちても他は出す）。ga4_call(body)->resp, gsc_call(body)->resp。

    2026-08-26 計測レビュー対応（修正1d）: GA4 と GSC で「対象週」が異なる（GSC は確定に
    数日かかるため、より過去の週を見る）ので、週の窓を2つ別々に受け取る。
    """
    warnings: list[str] = []
    failed_labels: list[str] = []

    def safe(fn, *args, label=""):
        # 2026-08-26 計測レビュー対応（修正1c）: 以前は失敗時に default={} を返しており、
        # parse_ga4_totals({}) と「本当にゼロ件だった」を区別できず、digest に偽の「0」が
        # 出ていた（fmt_int(None)="0"）。ここでは None を返し、呼び出し側で「取得失敗」と
        # 明示できるよう failed_labels に label を積む。
        try:
            return fn(*args)
        except Exception as exc:  # noqa: BLE001 - best-effort, digest は部分データでも成立させる
            warnings.append(f"{label}: {str(exc)[:120]}")
            failed_labels.append(label)
            return None

    cs, ce = ga4_weeks.cur_start.isoformat(), ga4_weeks.cur_end.isoformat()
    ps, pe = ga4_weeks.prev_start.isoformat(), ga4_weeks.prev_end.isoformat()
    gcs, gce = gsc_weeks.cur_start.isoformat(), gsc_weeks.cur_end.isoformat()
    gps, gpe = gsc_weeks.prev_start.isoformat(), gsc_weeks.prev_end.isoformat()

    # ---- GA4 ----
    raw_totals_cur = safe(ga4_call, ga4_totals_body(cs, ce), label="ga4.totals.cur")
    raw_totals_prev = safe(ga4_call, ga4_totals_body(ps, pe), label="ga4.totals.prev")
    ga4_totals_cur = parse_ga4_totals(raw_totals_cur) if raw_totals_cur is not None else None
    ga4_totals_prev = parse_ga4_totals(raw_totals_prev) if raw_totals_prev is not None else None

    top_pages_cur = [
        {"path": k, "views": v}
        for k, v in parse_ga4_rows(
            safe(ga4_call, ga4_dim_body(cs, ce, "pagePath", "screenPageViews", 10), label="ga4.pages.cur")
        )
    ]
    top_pages_prev = [
        {"path": k, "views": v}
        for k, v in parse_ga4_rows(
            safe(ga4_call, ga4_dim_body(ps, pe, "pagePath", "screenPageViews", 10), label="ga4.pages.prev")
        )
    ]

    events_cur = dict(
        parse_ga4_rows(safe(ga4_call, ga4_dim_body(cs, ce, "eventName", "eventCount", 25), label="ga4.events.cur"))
    )
    events_prev = dict(
        parse_ga4_rows(safe(ga4_call, ga4_dim_body(ps, pe, "eventName", "eventCount", 25), label="ga4.events.prev"))
    )

    channels_cur = [
        {"channel": k, "sessions": v}
        for k, v in parse_ga4_rows(
            safe(
                ga4_call,
                ga4_dim_body(cs, ce, "sessionDefaultChannelGroup", "sessions", 10),
                label="ga4.channels.cur",
            )
        )
    ]

    # ---- GSC（確定済みの週 = gsc_weeks を使う。修正1d） ----
    raw_gsc_totals_cur = safe(gsc_call, gsc_body(gcs, gce, [], 1), label="gsc.totals.cur")
    raw_gsc_totals_prev = safe(gsc_call, gsc_body(gps, gpe, [], 1), label="gsc.totals.prev")
    gsc_totals_cur = parse_gsc_totals(raw_gsc_totals_cur) if raw_gsc_totals_cur is not None else None
    gsc_totals_prev = parse_gsc_totals(raw_gsc_totals_prev) if raw_gsc_totals_prev is not None else None

    gsc_queries_cur = [
        {"query": r["key"], "clicks": r["clicks"], "impressions": r["impressions"]}
        for r in parse_gsc_rows(safe(gsc_call, gsc_body(gcs, gce, ["query"], 10), label="gsc.queries.cur"))
    ]
    gsc_queries_prev = [
        {"query": r["key"], "clicks": r["clicks"], "impressions": r["impressions"]}
        for r in parse_gsc_rows(safe(gsc_call, gsc_body(gps, gpe, ["query"], 10), label="gsc.queries.prev"))
    ]
    # rowLimit 200: 小規模サイト（直近28日37ユーザー実測）では取得できるページ数がこれで尽きる
    # ことが多いが、Search Analytics API は仕様上「上位N件」を返すのみで全行を保証しない
    # （API が返した上位行の snapshot であり、「全件」ではない）。
    raw_gsc_pages_cur = safe(gsc_call, gsc_body(gcs, gce, ["page"], 200), label="gsc.pages.cur")
    gsc_pages_cur = [
        {"page": r["key"], "clicks": r["clicks"], "impressions": r["impressions"]}
        for r in parse_gsc_rows(raw_gsc_pages_cur)
    ]
    # 修正2: query×page（検索語→ページ）。ダイジェストには上位3行だけ出すが、JSONには取得できた
    # 上位200行（rowLimit）を保持する（API が保証するのは上位N件までで、全件ではない）。
    gsc_query_page_cur = parse_gsc_query_page_rows(
        safe(gsc_call, gsc_body(gcs, gce, ["query", "page"], 200), label="gsc.query_page.cur")
    )

    # 2026-08-26 計測レビュー対応（第2ラウンド・修正3）: gsc.pages.cur の取得自体が失敗した場合、
    # parse 後は空リストになり qualified_clicks_total([]) が偽の 0.0 を返してしまう
    # （「取得失敗」と「実際に0件だった」を区別できない確定バグ）。raw レスポンスの成否で分岐する。
    if raw_gsc_pages_cur is not None:
        qualified_clicks, qualified_clicks_page_total = qualified_clicks_total(gsc_pages_cur)
    else:
        qualified_clicks, qualified_clicks_page_total = None, None

    ga4_status = compute_source_status(
        failed_labels,
        "ga4.",
        got_anything=bool(ga4_totals_cur is not None or top_pages_cur or events_cur or channels_cur),
    )
    gsc_status = compute_source_status(
        failed_labels,
        "gsc.",
        got_anything=bool(gsc_totals_cur is not None or gsc_queries_cur or gsc_pages_cur),
    )

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "weeks": {"ga4": ga4_weeks.as_dict(), "gsc": gsc_weeks.as_dict()},
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
            "query_page": {"cur": gsc_query_page_cur},
            "qualified_clicks": {"cur": qualified_clicks, "page_total": qualified_clicks_page_total},
        },
        "warnings": warnings,
        "data_quality": {"failed": failed_labels},
        # 2026-08-26 計測レビュー対応（第2ラウンド・修正5）: 保存JSON/CLI出力の解釈に必要な
        # メタデータ。schema_version は破壊的変更時にインクリメントする。
        "meta": {
            "schema_version": 2,
            "timezone": "Asia/Tokyo",
            "period": {"ga4": ga4_weeks.as_dict(), "gsc": gsc_weeks.as_dict()},
            "row_limits": {
                "ga4_top_pages": 10,
                "ga4_events": 25,
                "gsc_top_queries": 10,
                "gsc_top_pages": 200,
                "gsc_query_page": 200,
            },
            "source_status": {"ga4": ga4_status, "gsc": gsc_status},
        },
    }


# --------------------------------------------------------------------------
# ダイジェスト組み立て（純粋関数・テスト対象）
# --------------------------------------------------------------------------


def compose_digest(metrics: dict) -> str:
    weeks = metrics.get("weeks", {})
    ga4_w = weeks.get("ga4", {})
    gsc_w = weeks.get("gsc", {})
    cur_w = ga4_w.get("cur", {})
    prev_w = ga4_w.get("prev", {})
    gsc_cur_w = gsc_w.get("cur", {})
    ga4 = metrics.get("ga4", {})
    gsc = metrics.get("gsc", {})
    failed = set((metrics.get("data_quality") or {}).get("failed") or [])

    lines: list[str] = []
    lines.append("【めぐりび 週次アナリティクス】")
    lines.append(f"対象: {cur_w.get('start', '?')}〜{cur_w.get('end', '?')}")
    lines.append(f"（前週比: {prev_w.get('start', '?')}〜{prev_w.get('end', '?')}）")
    lines.append("")

    # --- GA4 サイト全体 ---
    gt = ga4.get("totals", {})
    gc = gt.get("cur") or {}
    gp = gt.get("prev") or {}
    ga4_cur_failed = "ga4.totals.cur" in failed
    ga4_prev_failed = "ga4.totals.prev" in failed
    lines.append("■ サイト全体（GA4）")
    lines.append(
        f"・アクティブユーザー: {fmt_metric_or_na(gc.get('activeUsers'), ga4_cur_failed)}"
        f"（前週比 {wow_str_or_na(gc.get('activeUsers'), gp.get('activeUsers'), ga4_cur_failed, ga4_prev_failed)}）"
    )
    lines.append(
        f"・セッション: {fmt_metric_or_na(gc.get('sessions'), ga4_cur_failed)}"
        f"（前週比 {wow_str_or_na(gc.get('sessions'), gp.get('sessions'), ga4_cur_failed, ga4_prev_failed)}）"
    )
    # 2026-08-26 計測レビュー対応（第2ラウンド・修正6）: PV(screenPageViews)は8/26に計測定義を
    # 変更したため、対象週と前週がその日をまたぐ場合は前期間比を出さない（水増しが混じるため）。
    pv_blocked = False
    try:
        cur_s = date.fromisoformat(cur_w["start"])
        cur_e = date.fromisoformat(cur_w["end"])
        prev_s = date.fromisoformat(prev_w["start"])
        prev_e = date.fromisoformat(prev_w["end"])
        pv_blocked = pv_delta_crosses_boundary(cur_s, cur_e, prev_s, prev_e)
    except (KeyError, ValueError):
        pv_blocked = False
    if pv_blocked:
        lines.append(
            f"・ページビュー: {fmt_metric_or_na(gc.get('screenPageViews'), ga4_cur_failed)}"
            "（前期間比 比較不可: 8/26にPV計測定義を変更したため）"
        )
    else:
        lines.append(
            f"・ページビュー: {fmt_metric_or_na(gc.get('screenPageViews'), ga4_cur_failed)}"
            f"（前週比 "
            f"{wow_str_or_na(gc.get('screenPageViews'), gp.get('screenPageViews'), ga4_cur_failed, ga4_prev_failed)}）"
        )
    lines.append("")

    # --- Search Console ---
    st = gsc.get("totals", {})
    sc = st.get("cur") or {}
    sp = st.get("prev") or {}
    gsc_cur_failed = "gsc.totals.cur" in failed
    gsc_prev_failed = "gsc.totals.prev" in failed
    lines.append("■ 検索流入（Search Console）")
    lines.append(
        f"・クリック: {fmt_metric_or_na(sc.get('clicks'), gsc_cur_failed)}"
        f"（前週比 {wow_str_or_na(sc.get('clicks'), sp.get('clicks'), gsc_cur_failed, gsc_prev_failed)}）"
    )
    lines.append(
        f"・表示回数: {fmt_metric_or_na(sc.get('impressions'), gsc_cur_failed)}"
        f"（前週比 {wow_str_or_na(sc.get('impressions'), sp.get('impressions'), gsc_cur_failed, gsc_prev_failed)}）"
    )
    if gsc_cur_failed:
        lines.append("・平均CTR: 取得失敗")
        lines.append("・平均掲載順位: 取得失敗")
    else:
        cur_ctr = float(sc.get("ctr") or 0) * 100.0
        prev_ctr = 0.0 if gsc_prev_failed else float(sp.get("ctr") or 0) * 100.0
        prev_ctr_str = "取得失敗" if gsc_prev_failed else f"{prev_ctr:.2f}%"
        lines.append(f"・平均CTR: {cur_ctr:.2f}%（前週 {prev_ctr_str}）")
        prev_pos_str = "取得失敗" if gsc_prev_failed else f"{float(sp.get('position') or 0):.1f}位"
        lines.append(f"・平均掲載順位: {float(sc.get('position') or 0):.1f}位（前週 {prev_pos_str}）")
    # 修正2: 有効検索クリック（home/store/area/stores/blog への非noindexページのクリック合計）。
    # 2026-08-26 計測レビュー対応（第2ラウンド・修正3）: qc.get('cur') は gsc.pages.cur の取得が
    # 失敗すると None になる（実際の0件と区別するため）。fmt_int(None) の偽の "0" を出さない。
    qc = gsc.get("qualified_clicks") or {}
    qualified_failed = qc.get("cur") is None
    lines.append(
        f"・有効クリック: {fmt_metric_or_na(qc.get('cur'), qualified_failed)}"
        f"（全クリック {fmt_metric_or_na(sc.get('clicks'), gsc_cur_failed)}）"
    )
    # 修正1d: GSC は確定に数日かかるため対象週が GA4 とズレる。ここで明記する。
    lines.append(
        f"・GSC確定週: {format_md(gsc_cur_w.get('start', cur_w.get('start', '')))}"
        f"〜{format_md(gsc_cur_w.get('end', cur_w.get('end', '')))}"
        "（検索データは数日遅れで確定するため、GA4の週とはズレます）"
    )
    lines.append("")

    # --- 今週のハイライト ---
    lines.append("■ 今週のハイライト")
    pg = top_growth(ga4.get("top_pages", {}).get("cur"), ga4.get("top_pages", {}).get("prev"), "path", "views")
    if pg:
        item, delta = pg
        lines.append(f"・最も伸びたページ: {item.get('path')}（+{fmt_int(delta)}PV）")
    qg = top_growth(
        gsc.get("top_queries", {}).get("cur"), gsc.get("top_queries", {}).get("prev"), "query", "clicks"
    )
    if qg:
        item, delta = qg
        lines.append(f"・最も伸びた検索クエリ: 「{item.get('query')}」（+{fmt_int(delta)}クリック）")
    if not pg and not qg:
        lines.append("・（今週伸びたページ/クエリはありませんでした）")
    lines.append("")

    # --- 検索語→ページ TOP3（修正2） ---
    query_page_cur = gsc.get("query_page", {}).get("cur") or []
    top_query_page = sorted(query_page_cur, key=lambda r: r.get("clicks") or 0, reverse=True)[:3]
    if top_query_page:
        # 2026-08-26 計測レビュー対応（第2ラウンド・修正5）: Search Analytics API は上位N件
        # （rowLimit）を返すのみで全行を保証しない。「全件」ではなく上位からの抜粋と明記する。
        lines.append("■ 検索語→ページ TOP3（APIの取得上位行からの抜粋。全件ではありません）")
        for row in top_query_page:
            page_path = urllib.parse.urlparse(row.get("page") or "").path or row.get("page") or ""
            lines.append(f"・「{row.get('query')}」→ {page_path}（{fmt_int(row.get('clicks'))}クリック）")
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
    # 2026-08-26 計測レビュー対応（第2ラウンド・修正6）: report_read（旧名）は表示専用で
    # report_view へ合算する（生JSON側の events dict はここでは変更しない、上の metrics には
    # 内訳がそのまま残る）。
    events_cur = canonical_events_for_display(ga4.get("events", {}).get("cur", {}) or {})
    events_prev = canonical_events_for_display(ga4.get("events", {}).get("prev", {}) or {})
    shown = [(name, events_cur[name]) for name in KNOWN_CUSTOM_EVENTS if name in events_cur]
    if shown:
        lines.append("■ イベント利用状況（サイト内アクション）")
        for name, cnt in shown:
            lines.append(f"・{name}: {fmt_int(cnt)}（前週比 {wow_str(cnt, events_prev.get(name))}）")
        lines.append("")

    # --- 注記 ---
    if metrics.get("warnings"):
        if failed:
            lines.append(f"※ 一部データの取得に失敗しました（対象: {', '.join(sorted(failed))}）。詳細はログを参照。")
        else:
            lines.append("※ 一部データの取得に失敗しました（詳細はログを参照）。")
    lines.append("※ Search Console の直近2日は集計途中の場合があります。")
    # 2026-09-06 訂正: 以前ここは「本レポートは非公開（private バケットに保存）」と断言していたが、
    # `ml-models` バケットは実測で匿名 GET に 200 を返す＝公開設定であり事実誤りだった。オーナーが
    # 週次で実際に読むのはこの digest だけなので、ここが嘘だと誰も気づけない。LINE 向けに短く、
    # かつ「何をすればよいか」（private 化の手順の在り処）まで書く。
    lines.append("※ 数値は Supabase Storage に保存。バケットは公開設定のため匿名で読めます（private 化: docs/ANALYTICS_SETUP.md §9）。")

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
# 永続化（Supabase Storage：put は scripts/_supabase_common.py の共有実装）
# --------------------------------------------------------------------------


def _anon_storage_get_status(bucket: str, path: str, supabase_url: str) -> int | None:
    """認証ヘッダ無しで Storage の public URL 形式へ1回だけ GET する。2026-08-26 計測レビュー
    対応（第2ラウンド・修正4）。ネットワーク例外・タイムアウトは None（判定不能）を返す。
    """
    url = f"{supabase_url}/storage/v1/object/public/{bucket}/{path}"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.getcode()
    except urllib.error.HTTPError as exc:
        return exc.code
    except Exception:  # noqa: BLE001 - ネットワーク断・DNS失敗等。判定不能として扱う。
        return None


def bucket_appears_public(bucket: str, supabase_url: str, probe_path: str = "forecast/latest/metadata.json") -> bool:
    """バケットが匿名GETで200を返すか（＝公開設定の疑い）を判定する。

    2026-08-26 計測レビュー対応（第2ラウンド・修正4）: 検索語を含むデータをアップロードする前に、
    同バケットの匿名GET（Authorization無しの public URL 形式）を1回試みる。200＝公開設定の疑い、
    401/403/404、または判定不能（例外）は私設と判断して続行する（依頼どおりの判定基準）。
    probe_path は分析データではなく、常時存在する既知オブジェクト（forecast モデルの
    metadata.json、CLAUDE.md §1 記載のStorageレイアウトを参照）を使う。分析データ自体を
    プローブに使うと「まだアップロードしていないので当然404」になり判定できないため。
    """
    status = _anon_storage_get_status(bucket, probe_path, supabase_url)
    return status == 200


def _redact_search_terms(metrics: dict) -> dict:
    """検索語を含む部分（GSC top_queries / query_page）を除いたコピーを返す。公開バケット疑いの
    ときだけ使う（fail-closed。2026-08-26 計測レビュー対応・修正4）。"""
    redacted = json.loads(json.dumps(metrics, ensure_ascii=False))
    gsc = redacted.get("gsc")
    if isinstance(gsc, dict):
        if "top_queries" in gsc:
            gsc["top_queries"] = "[redacted: public bucket probe returned 200]"
        if "query_page" in gsc:
            gsc["query_page"] = "[redacted: public bucket probe returned 200]"
    return redacted


def upload_metrics(metrics: dict, weeks: WeekWindows) -> str | None:
    """生 JSON を Storage バケットへ。SUPABASE 未設定なら None（警告のみ、失敗にしない）。

    2026-08-26 計測レビュー対応（第2ラウンド・修正4）:
    - バケットが匿名GETで200を返す（公開設定の疑い）場合、検索語を含む部分をredactしてから
      アップロードする（fail-closed）。redactした旨を metrics["warnings"] にも積み、
      呼び出し側（main）の exit code 判定に反映させる。
    - `data_quality.failed` が非空（部分失敗）のときは、正本パス
      `analytics/weekly/<週初>.json` を上書きせず `<週初>_partial.json` へ保存する
      （壊れた/欠けた成果物で良品を上書きしない）。
    """
    conf = _supabase_conf()
    bucket = (os.environ.get("FORECAST_MODEL_BUCKET") or DEFAULT_BUCKET).strip()
    if conf is None:
        print("[analytics] SUPABASE 未設定のため生JSONの保存をスキップしました。")
        return None
    supabase_url, key = conf

    payload_metrics = metrics
    if bucket_appears_public(bucket, supabase_url):
        print(
            f"[analytics][warn] Storage bucket '{bucket}' が匿名GETで200を返しました"
            "（公開設定の疑い）。検索語を含む部分をredactしてアップロードします（修正4）。"
        )
        payload_metrics = _redact_search_terms(metrics)
        metrics.setdefault("warnings", []).append(
            f"public_bucket_probe: bucket '{bucket}' returned 200 on anonymous GET; search terms redacted"
        )

    is_partial = bool((metrics.get("data_quality") or {}).get("failed"))
    week_key = weeks.cur_start.isoformat()
    path = f"analytics/weekly/{week_key}{'_partial' if is_partial else ''}.json"
    _storage_put(bucket, path, json.dumps(payload_metrics, ensure_ascii=False).encode("utf-8"), supabase_url, key)
    dest = f"{bucket}/{path}"
    if is_partial:
        print(f"[analytics][warn] 部分失敗のため正本パスへは保存せず、{dest} に保存しました。")
    else:
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

    try:
        token = google_access_token(sa_path, [GA4_SCOPE, GSC_SCOPE])
    except Exception as exc:  # noqa: BLE001 - 2026-08-26 計測レビュー対応（修正1c）:
        # 以前は creds.refresh() の失敗（鍵が不正・失効・ネットワーク断など）が未捕捉のまま
        # 生の traceback で落ちていた。Task Scheduler の「前回の結果」欄で異常に気付けるよう、
        # 分かりやすい日本語メッセージ + 非ゼロ終了にする（google-auth 未インストールの場合と
        # 違い、これは「設定ミス/一時障害」なので exit 0 の graceful no-op にはしない）。
        print(f"[analytics][error] Google 認証に失敗しました: {exc}")
        print("  鍵ファイル(secrets/ga-service-account.json)の有効期限・内容を確認してください。")
        return 1
    if token is None:
        print(
            "[analytics] google-auth が未インストールのため認証できません。\n"
            "  `pip install -r requirements.txt` を実行してから再度お試しください。\n"
            "  （手順は docs/ANALYTICS_SETUP.md を参照）"
        )
        return 0

    now_jst = datetime.now(JST)
    ga4_weeks = last_full_week(now_jst)
    gsc_weeks = last_confirmed_week(now_jst)
    print(
        f"[analytics] GA4対象週 {ga4_weeks.cur_start}〜{ga4_weeks.cur_end}"
        f"（前週 {ga4_weeks.prev_start}〜{ga4_weeks.prev_end}）、"
        f"GSC確定週 {gsc_weeks.cur_start}〜{gsc_weeks.cur_end}"
        f"（前週 {gsc_weeks.prev_start}〜{gsc_weeks.prev_end}）を集計します。"
    )

    def ga4_call(body: dict) -> dict:
        return _ga4_run_report(token, property_id, body)

    def gsc_call(body: dict) -> dict:
        return _gsc_query(token, site_url, body)

    metrics = fetch_metrics(ga4_weeks, gsc_weeks, ga4_call, gsc_call)
    digest = compose_digest(metrics)

    if args.dry_run:
        print("\n===== DRY RUN: 生成したダイジェスト =====\n")
        print(digest)
        if metrics.get("warnings"):
            print("\n[warn] " + " / ".join(metrics["warnings"]))
            return 3
        return 0

    # 生 JSON を Storage バケットへ、ダイジェストをローカルへ（保存先ファイル名は GA4 週基準、従来どおり）。
    # upload_metrics は失敗時に metrics["warnings"] へ追記しうる（公開バケット疑いのredact等・修正4）
    # ため、必ず終了コード判定の前に呼ぶ。
    upload_metrics(metrics, ga4_weeks)
    log_path = write_local_log(digest, ga4_weeks)

    # LINE 送信（未配線でも失敗にしない）。
    if send_line_push(digest):
        print(f"[analytics] LINE でダイジェストを送信しました。ローカル控え: {log_path}")
    else:
        print(f"[analytics] LINE未配線（LINE_USER_ID 未設定）— digestは {log_path} に保存しました。")

    # 2026-08-26 計測レビュー対応（第2ラウンド・修正4）: 0=完全成功のみ、3=部分取得失敗または
    # 公開バケット疑いでのredact等（生成はできたが完全ではない）、1=認証・依存・主要ソース全滅
    # （既存どおり、この関数より前で return 済み）。
    if metrics.get("warnings"):
        print("[warn] " + " / ".join(metrics["warnings"]))
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
