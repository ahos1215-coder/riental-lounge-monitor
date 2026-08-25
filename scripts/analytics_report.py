"""OWNER-ONLY 最新分析 CLI for めぐりび (meguribi.jp)。読み取り専用（保存・送信は一切しない）。

何をするスクリプトか
--------------------
`scripts/analytics_weekly_report.py`（週次ダイジェスト、月曜09:00に自動実行・Supabase保存・
LINE送信）とは別に、オーナーが手元で好きなタイミングで GA4 / Search Console の最新状況を
見るための CLI。**完全 read-only**（Supabase への保存・LINE送信・ファイル書き込みは行わない。
`--publish` の類も意図的に持たない）。週報と同じ純粋関数（週の窓計算・parse・ページ分類・
指名判定・順位帯・有効検索クリック等）を `scripts/analytics_weekly_report.py` から import して
使う（コピペしない。ロジックが2箇所でズレる事故を避けるため）。

2026-08-26 計測レビュー対応で新規作成。

使い方
------
    python scripts/analytics_report.py --mode latest --days 28
    python scripts/analytics_report.py --mode range --start 2026-07-01 --end 2026-07-31 --compare previous
    python scripts/analytics_report.py --format json --days 7

引数
----
    --mode latest|range        既定 latest（as_of から遡って --days 日）
    --days 7|28|90              既定 28（--mode latest のときだけ使う）
    --start / --end             YYYY-MM-DD（--mode range のとき必須）
    --compare previous          直前の同じ長さの期間と比較（deltas を出力）
    --format json|markdown      既定 markdown
    --as-of YYYY-MM-DD          「今日」を固定する（テスト・過去日基準の確認用）

GA4 は当日を含む期間もそのまま取得するが、直近2日（today/yesterday）を含む期間には
`provisional: true` を明示する（GA4 の直近データは後から数値が動くことがあるため）。
GSC は `dataState="all"`（速報込み）で取得し、レスポンスの metadata から確定日が読めれば
それを使い、読めなければ「実行日の3日前より新しい日は未確定」という規約ベースの推定に
フォールバックする（`scripts/analytics_weekly_report.py::last_confirmed_week` の
`min_lag_days=3` と同じ規約）。未確定日を 0 件と表示することはしない
（`provisional_dates` に列挙し、markdown 上も「未確定」と明記する）。

終了コード
----------
    0 = 全ソース取得成功
    3 = 一部のクエリが取得失敗（部分データで出力はできた）
    1 = 致命的失敗（認証情報が無い/認証失敗/GA4とGSC両方が全滅/引数不正）

必要な環境変数は `scripts/analytics_weekly_report.py` と共通（GA4_PROPERTY_ID /
GA_SERVICE_ACCOUNT_JSON / GSC_SITE_URL。docs/ANALYTICS_SETUP.md 参照）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# scripts/analytics_weekly_report.py の純粋関数を再利用する（コピペしない）。pytest 経由
# （pythonpath=. で `scripts` が namespace package として見える）では package-qualified import を
# 優先し、`python scripts/analytics_report.py` の直接実行（scripts/ 自体が sys.path[0]）では
# ベアインポートにフォールバックする。scripts/_supabase_common.py の docstring に書かれている
# 「呼び出し側が sys.path を通した上でベアインポートする」規約と同じ考え方。
try:
    from scripts import analytics_weekly_report as awr  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - 直接実行時のパス
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import analytics_weekly_report as awr  # type: ignore[import-not-found,no-redef]

JST = awr.JST

NO_CREDENTIALS_HINT = (
    "[analytics-report] アナリティクスの認証情報が見つかりません（未セットアップ）。\n"
    "  必要なもの: GA4_PROPERTY_ID（.env.local）と secrets/ga-service-account.json（鍵ファイル）。\n"
    "  有効化の手順は docs/ANALYTICS_SETUP.md を参照してください。\n"
    "  （このコマンドは診断用の read-only CLI のため、週報と違い exit 1 で終了します。）"
)


# --------------------------------------------------------------------------
# 期間計算（純粋関数・テスト対象）
# --------------------------------------------------------------------------


def resolve_period(mode: str, days: int, start: str | None, end: str | None, as_of: date) -> tuple[date, date]:
    """(start, end) を返す。--mode range は --start/--end 必須、--mode latest は as_of から遡る。"""
    if mode == "range":
        if not start or not end:
            raise ValueError("--mode range には --start と --end の両方の指定が必要です。")
        s = date.fromisoformat(start)
        e = date.fromisoformat(end)
        if s > e:
            raise ValueError(f"--start（{start}）は --end（{end}）以前の日付にしてください。")
        return s, e
    if mode != "latest":
        raise ValueError(f"未知の --mode です: {mode}（latest / range のいずれかを指定してください）。")
    e = as_of
    s = e - timedelta(days=days - 1)
    return s, e


def previous_period(start: date, end: date) -> tuple[date, date]:
    """同じ日数の直前の期間を返す（--compare previous 用）。"""
    length = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=length - 1)
    return prev_start, prev_end


def ga4_provisional_flag(period_end: date, as_of: date) -> bool:
    """期間の終端が as_of の直近2日（today/yesterday）に懸かっていれば True。"""
    return period_end >= as_of - timedelta(days=1)


def ga4_provisional_dates(period_start: date, period_end: date, as_of: date) -> list[str]:
    """要求期間のうち、GA4 側でまだ数値が動きうる日（today/yesterday）の一覧。"""
    cutoff_from = as_of - timedelta(days=1)
    start = max(period_start, cutoff_from)
    end = min(period_end, as_of)
    out: list[str] = []
    d = start
    while d <= end:
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def gsc_availability(resp: dict | None, as_of: date, lag_days: int = 3) -> dict:
    """GSC レスポンスの metadata から確定日を読み取る。取れなければ規約ベースにフォールバック。

    searchAnalytics.query の通常レスポンスには per-request の確定日メタデータが無いことが
    多い（未提供）。取れた場合だけ優先して使い、取れなければ「実行日の lag_days 日前より
    新しい日は未確定」という規約（last_confirmed_week の min_lag_days と同じ考え方）を使う。
    """
    meta = (resp or {}).get("metadata") or {}
    first_incomplete = meta.get("first_incomplete_date") or meta.get("firstIncompleteDate")
    if first_incomplete:
        try:
            incomplete_from = date.fromisoformat(first_incomplete)
            return {"available_through": (incomplete_from - timedelta(days=1)).isoformat(), "source": "metadata"}
        except ValueError:
            pass
    return {"available_through": (as_of - timedelta(days=lag_days)).isoformat(), "source": "rule"}


def provisional_dates_in_period(start: date, end: date, available_through: date) -> list[str]:
    """要求期間のうち、available_through より新しい（＝未確定の可能性がある）日の一覧。"""
    out: list[str] = []
    d = max(start, available_through + timedelta(days=1))
    while d <= end:
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def compute_deltas(cur: dict | None, prev: dict | None) -> dict | None:
    """cur/prev（同じキーを持つ totals dict）から {key: {delta, pct}} を作る。片方が無ければ None。"""
    if cur is None or prev is None:
        return None
    out: dict = {}
    for key, cur_val in cur.items():
        delta, pct = awr.wow_delta(cur_val, prev.get(key))
        out[key] = {"delta": delta, "pct": pct}
    return out


def position_bucket_counts(rows: list[dict]) -> dict[str, int]:
    """GSC クエリ行のリストを順位帯(1-3/4-10/11-20/21+)ごとのクエリ数に集計する。"""
    counts = {"1-3": 0, "4-10": 0, "11-20": 0, "21+": 0}
    for row in rows or []:
        counts[awr.position_bucket(row.get("position"))] += 1
    return counts


# --------------------------------------------------------------------------
# 指標の取得（ネットワーク境界は ga4_call / gsc_call に注入 → テストは fake を渡す）
# --------------------------------------------------------------------------


def fetch_report(period: tuple[date, date], as_of: date, compare: bool, ga4_call, gsc_call) -> dict:
    warnings: list[str] = []
    failed: list[str] = []

    def safe(fn, *args, label=""):
        try:
            return fn(*args)
        except Exception as exc:  # noqa: BLE001 - best-effort。1クエリの失敗で全滅させない。
            warnings.append(f"{label}: {str(exc)[:160]}")
            failed.append(label)
            return None

    start, end = period
    s, e = start.isoformat(), end.isoformat()

    # ---- GA4 ----
    raw_totals = safe(ga4_call, awr.ga4_totals_body(s, e), label="ga4.totals")
    ga4_totals = awr.parse_ga4_totals(raw_totals) if raw_totals is not None else None

    ga4_landing = [
        {"page": k, "sessions": v}
        for k, v in awr.parse_ga4_rows(
            safe(ga4_call, awr.ga4_dim_body(s, e, "landingPage", "sessions", 10), label="ga4.landing_pages")
        )
    ]
    ga4_channels = [
        {"channel": k, "sessions": v}
        for k, v in awr.parse_ga4_rows(
            safe(
                ga4_call,
                awr.ga4_dim_body(s, e, "sessionDefaultChannelGroup", "sessions", 10),
                label="ga4.channels",
            )
        )
    ]
    ga4_events = dict(
        awr.parse_ga4_rows(safe(ga4_call, awr.ga4_dim_body(s, e, "eventName", "eventCount", 30), label="ga4.events"))
    )

    ga4_prev_totals = None
    if compare:
        ps, pe = previous_period(start, end)
        raw_prev = safe(
            ga4_call, awr.ga4_totals_body(ps.isoformat(), pe.isoformat()), label="ga4.totals.previous"
        )
        ga4_prev_totals = awr.parse_ga4_totals(raw_prev) if raw_prev is not None else None

    ga4_section = {
        "requested_period": {"start": s, "end": e},
        "provisional": ga4_provisional_flag(end, as_of),
        "provisional_dates": ga4_provisional_dates(start, end, as_of),
        "totals": ga4_totals,
        "previous": ga4_prev_totals,
        "deltas": compute_deltas(ga4_totals, ga4_prev_totals) if compare else None,
        "landing_pages": ga4_landing,
        "channels": ga4_channels,
        "events": ga4_events,
    }

    # ---- GSC（dataState="all" = 速報込み。修正2/analytics_report固有） ----
    raw_gsc_totals = safe(gsc_call, awr.gsc_body(s, e, [], 1, data_state="all"), label="gsc.totals")
    gsc_totals = awr.parse_gsc_totals(raw_gsc_totals) if raw_gsc_totals is not None else None
    availability = gsc_availability(raw_gsc_totals, as_of)
    available_through = date.fromisoformat(availability["available_through"])
    prov_dates = provisional_dates_in_period(start, end, available_through)

    gsc_queries = [
        {"query": r["key"], "clicks": r["clicks"], "impressions": r["impressions"], "position": r["position"]}
        for r in awr.parse_gsc_rows(safe(gsc_call, awr.gsc_body(s, e, ["query"], 25, data_state="all"), label="gsc.queries"))
    ]
    gsc_pages = [
        {"page": r["key"], "clicks": r["clicks"], "impressions": r["impressions"]}
        for r in awr.parse_gsc_rows(safe(gsc_call, awr.gsc_body(s, e, ["page"], 200, data_state="all"), label="gsc.pages"))
    ]
    gsc_query_page = awr.parse_gsc_query_page_rows(
        safe(gsc_call, awr.gsc_body(s, e, ["query", "page"], 200, data_state="all"), label="gsc.query_page")
    )
    qualified, page_total = awr.qualified_clicks_total(gsc_pages)

    gsc_prev_totals = None
    if compare:
        ps, pe = previous_period(start, end)
        raw_gsc_prev = safe(
            gsc_call,
            awr.gsc_body(ps.isoformat(), pe.isoformat(), [], 1, data_state="all"),
            label="gsc.totals.previous",
        )
        gsc_prev_totals = awr.parse_gsc_totals(raw_gsc_prev) if raw_gsc_prev is not None else None

    gsc_section = {
        "requested_period": {"start": s, "end": e},
        "available_through": availability["available_through"],
        "provisional": bool(prov_dates),
        "provisional_dates": prov_dates,
        "totals": gsc_totals,
        "previous": gsc_prev_totals,
        "deltas": compute_deltas(gsc_totals, gsc_prev_totals) if compare else None,
        "top_queries": gsc_queries,
        "top_pages": gsc_pages,
        "query_page": gsc_query_page,
        "qualified_clicks": {"qualified": qualified, "total": page_total},
        "position_buckets": position_bucket_counts(gsc_queries),
    }

    # ソースごとの状態: 何かひとつでも取れていれば partial、主要データ(totals)すら
    # 全滅していれば failed、失敗が無ければ ok。
    def _status(prefix: str, got_anything: bool) -> str:
        source_failed = [label for label in failed if label.startswith(prefix)]
        if not source_failed:
            return "ok"
        return "partial" if got_anything else "failed"

    ga4_status = _status("ga4.", bool(ga4_landing or ga4_channels or ga4_events or ga4_totals is not None))
    gsc_status = _status("gsc.", bool(gsc_queries or gsc_pages or gsc_totals is not None))

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "as_of_jst": as_of.isoformat(),
        "ga4": ga4_section,
        "gsc": gsc_section,
        "data_quality": {
            "source_status": {"ga4": ga4_status, "gsc": gsc_status},
            "warnings": warnings,
            "partial_failures": failed,
        },
    }


# --------------------------------------------------------------------------
# markdown 整形（純粋関数・テスト対象）
# --------------------------------------------------------------------------


def _fmt_or_na(value) -> str:
    return "N/A" if value is None else awr.fmt_int(value)


def compose_markdown(report: dict) -> str:
    lines: list[str] = []
    lines.append("# めぐりび アナリティクス最新分析")
    lines.append("")
    lines.append(f"- 生成時刻(UTC): {report.get('generated_at_utc')}")
    lines.append(f"- 基準日(JST, as_of): {report.get('as_of_jst')}")
    lines.append("")

    ga4 = report.get("ga4", {})
    period = ga4.get("requested_period", {})
    lines.append(f"## GA4（{period.get('start')}〜{period.get('end')}）")
    if ga4.get("provisional"):
        dates = "、".join(ga4.get("provisional_dates") or [])
        lines.append(f"※ 直近日を含みます（速報値・後で数値が動くことがあります）: {dates}")
    totals = ga4.get("totals")
    if totals is None:
        lines.append("- 取得失敗（詳細は下部「データ品質」を参照）")
    else:
        lines.append(f"- アクティブユーザー: {_fmt_or_na(totals.get('activeUsers'))}")
        lines.append(f"- セッション: {_fmt_or_na(totals.get('sessions'))}")
        lines.append(f"- ページビュー: {_fmt_or_na(totals.get('screenPageViews'))}")
    deltas = ga4.get("deltas")
    if deltas:
        for key, label in (
            ("activeUsers", "アクティブユーザー"),
            ("sessions", "セッション"),
            ("screenPageViews", "ページビュー"),
        ):
            d = deltas.get(key)
            if d and d.get("pct") is not None:
                sign = "+" if d["delta"] >= 0 else ""
                lines.append(f"  - 前期間比 {label}: {sign}{d['pct']:.1f}%")
    if ga4.get("landing_pages"):
        lines.append("")
        lines.append("### ランディングページ TOP10")
        for i, row in enumerate(ga4["landing_pages"][:10], 1):
            lines.append(f"{i}. {row.get('page')} … {_fmt_or_na(row.get('sessions'))}")
    if ga4.get("channels"):
        lines.append("")
        lines.append("### 流入チャネル")
        for row in ga4["channels"]:
            lines.append(f"- {row.get('channel')}: {_fmt_or_na(row.get('sessions'))}")
    if ga4.get("events"):
        shown = [(name, ga4["events"][name]) for name in awr.KNOWN_CUSTOM_EVENTS if name in ga4["events"]]
        if shown:
            lines.append("")
            lines.append("### イベント（サイト内アクション）")
            for name, cnt in shown:
                lines.append(f"- {name}: {_fmt_or_na(cnt)}")

    lines.append("")
    gsc = report.get("gsc", {})
    gperiod = gsc.get("requested_period", {})
    lines.append(f"## Search Console（{gperiod.get('start')}〜{gperiod.get('end')}）")
    lines.append(f"- 確定済み: 〜{gsc.get('available_through')}")
    if gsc.get("provisional_dates"):
        lines.append(f"※ 未確定の可能性がある日（参考値）: {', '.join(gsc['provisional_dates'])}")
    gtotals = gsc.get("totals")
    if gtotals is None:
        lines.append("- 取得失敗（詳細は下部「データ品質」を参照）")
    else:
        lines.append(f"- クリック: {_fmt_or_na(gtotals.get('clicks'))}")
        lines.append(f"- 表示回数: {_fmt_or_na(gtotals.get('impressions'))}")
        ctr = gtotals.get("ctr")
        lines.append(f"- 平均CTR: {'N/A' if ctr is None else f'{ctr * 100:.2f}%'}")
        pos = gtotals.get("position")
        lines.append(f"- 平均掲載順位: {'N/A' if pos is None else f'{pos:.1f}位'}")
    gdeltas = gsc.get("deltas")
    if gdeltas:
        for key, label in (("clicks", "クリック"), ("impressions", "表示回数")):
            d = gdeltas.get(key)
            if d and d.get("pct") is not None:
                sign = "+" if d["delta"] >= 0 else ""
                lines.append(f"  - 前期間比 {label}: {sign}{d['pct']:.1f}%")
    # 「全クリック」は正確な合計値（totals クエリ由来）を使う。qualified_clicks.total は
    # ページ内訳（rowLimit 200 でキャップ）の合計で、長い尾を持つサイトだと totals よりわずかに
    # 少なくなりうるため、表示上の分母には使わない（週報 compose_digest と揃えた挙動）。
    qc = gsc.get("qualified_clicks") or {}
    lines.append(
        f"- 有効クリック: {_fmt_or_na(qc.get('qualified'))}（全クリック {_fmt_or_na((gtotals or {}).get('clicks'))}）"
    )
    buckets = gsc.get("position_buckets") or {}
    if buckets:
        lines.append(
            "- 順位帯（クエリ数）: "
            f"1-3={buckets.get('1-3', 0)} / 4-10={buckets.get('4-10', 0)} / "
            f"11-20={buckets.get('11-20', 0)} / 21+={buckets.get('21+', 0)}"
        )
    top_queries = gsc.get("top_queries") or []
    if top_queries:
        lines.append("")
        lines.append("### 検索クエリ TOP10")
        for i, row in enumerate(top_queries[:10], 1):
            branded = "指名" if awr.is_branded_query(row.get("query") or "") else "一般"
            lines.append(f"{i}. 「{row.get('query')}」（{branded}） … {_fmt_or_na(row.get('clicks'))}クリック")
    query_page = gsc.get("query_page") or []
    if query_page:
        top_qp = sorted(query_page, key=lambda r: r.get("clicks") or 0, reverse=True)[:5]
        lines.append("")
        lines.append("### 検索語→ページ TOP5")
        for row in top_qp:
            page_path = urllib.parse.urlparse(row.get("page") or "").path or (row.get("page") or "")
            lines.append(f"- 「{row.get('query')}」→ {page_path}（{_fmt_or_na(row.get('clicks'))}クリック）")

    dq = report.get("data_quality", {})
    if dq.get("warnings"):
        lines.append("")
        lines.append("## データ品質")
        lines.append(f"- 取得失敗ソース: {', '.join(dq.get('partial_failures') or [])}")
        for w in dq["warnings"]:
            lines.append(f"  - {w}")

    return "\n".join(lines)


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    awr._configure_stdout_utf8()
    ap = argparse.ArgumentParser(
        description="めぐりび アナリティクス最新分析（オーナー専用・read-only）"
    )
    ap.add_argument("--mode", choices=["latest", "range"], default="latest")
    ap.add_argument("--days", type=int, choices=[7, 28, 90], default=28)
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--compare", choices=["previous"], default=None)
    ap.add_argument("--format", choices=["json", "markdown"], default="markdown")
    ap.add_argument("--as-of", dest="as_of", default=None, help="YYYY-MM-DD（テスト・過去日基準の確認用）")
    args = ap.parse_args(argv)

    awr._load_env()

    property_id = (os.environ.get("GA4_PROPERTY_ID") or "").strip()
    sa_path = Path(
        os.environ.get("GA_SERVICE_ACCOUNT_JSON")
        or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        or awr.DEFAULT_SA_PATH
    )
    site_url = (os.environ.get("GSC_SITE_URL") or awr.DEFAULT_GSC_SITE_URL).strip()

    if not awr._credentials_present(property_id, sa_path):
        print(NO_CREDENTIALS_HINT)
        return 1

    try:
        token = awr.google_access_token(sa_path, [awr.GA4_SCOPE, awr.GSC_SCOPE])
    except Exception as exc:  # noqa: BLE001 - 週報と同じ方針（修正1c）。診断用CLIなので exit 1。
        print(f"[analytics-report][error] Google 認証に失敗しました: {exc}")
        return 1
    if token is None:
        print(
            "[analytics-report] google-auth が未インストールのため認証できません。\n"
            "  `pip install -r requirements.txt` を実行してから再度お試しください。"
        )
        return 1

    if args.as_of:
        try:
            as_of = date.fromisoformat(args.as_of)
        except ValueError:
            print(f"[analytics-report][error] --as-of の形式が不正です: {args.as_of}（YYYY-MM-DD で指定）。")
            return 1
    else:
        as_of = datetime.now(JST).date()

    try:
        period = resolve_period(args.mode, args.days, args.start, args.end, as_of)
    except ValueError as exc:
        print(f"[analytics-report][error] {exc}")
        return 1

    def ga4_call(body: dict) -> dict:
        return awr._ga4_run_report(token, property_id, body)

    def gsc_call(body: dict) -> dict:
        return awr._gsc_query(token, site_url, body)

    report = fetch_report(period, as_of, args.compare == "previous", ga4_call, gsc_call)

    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(compose_markdown(report))

    status = report["data_quality"]["source_status"]
    if status["ga4"] == "failed" and status["gsc"] == "failed":
        return 1
    if report["data_quality"]["warnings"]:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
