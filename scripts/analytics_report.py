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
GSC は `dataState="all"`（速報込み）で取得する。確定日は totals レスポンスの metadata では
なく、`dimensions=["date"]` + `dataState="all"` の専用プローブ（`gsc_freshness_probe_body`）
から読む（公式仕様上、確定日メタデータは date dimension 付きのレスポンスでしか返らないため。
2026-08-26 計測レビュー第2ラウンド 修正1）。プローブが失敗/読めなければ「実行日の3日前より
新しい日は未確定」という規約ベースの推定にフォールバックする（`available_through_source` に
`metadata`/`rule` を明示。`scripts/analytics_weekly_report.py::last_confirmed_week` の
`min_lag_days=3` と同じ規約）。未確定日を 0 件と表示することはしない
（`provisional_dates` に列挙し、markdown 上も「未確定」と明記する）。

前期間比（`--compare previous`）は、速報を含む現在期間をそのまま前期間と%比較しない。
確定分同士（現在期間の確定部分 vs 同じ長さの直前期間）で別途「確定ベースの比較」を計算し
（`stable_comparison`）、markdown/JSON の `deltas` はこちらを使う（生の totals は速報込みの
まま別途表示。2026-08-26 計測レビュー第2ラウンド 修正2）。PV(screenPageViews) は 8/26 に
計測定義を変更したため、比較対象の期間がこの日をまたぐ場合は screenPageViews の delta だけ
「比較不可」と明示する（他の指標には適用しない。修正6）。

2026-09-06 表示修正: 上記の設計（確定分同士で比べる）は正しいが、markdown 上で
「要求期間の合計値」と「確定期間どうしの増減率」が注記だけを挟んで隣り合っており、
実際に読み手が「28日の合計と、その28日の前期間比」と誤読する事故が起きた（横ばいのものを
「増えた」と読んだ）。設計は変えず、**増減率の行そのものに実際の比較期間と日数を必ず併記**し
（`comparison_span_label`）、`※` の注記も「上の合計と下の増減率は期間が異なる」と明示する
文言に変えた。GA4/GSC 両方に同じ対応を入れている。

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


def gsc_freshness_probe_body(as_of: date, lookback_days: int = 10) -> dict:
    """GSC の確定日メタデータを読むための専用プローブのリクエストボディ。

    2026-08-26 計測レビュー対応（第2ラウンド・修正1）: 公式仕様では `metadata.first_incomplete_date`
    は `dataState="all"` かつ `dimensions=["date"]` のレスポンスでしか返らない。以前は dimension
    無しの totals リクエストへ `dataState="all"` を付けるだけで metadata を読もうとしており、
    本番ではほぼ常に rule フォールバックしか効いていなかった（本当の意味でのバグ）。ここで
    totals とは別に date dimension 専用のプローブを1回追加リクエストする。直近 lookback_days
    日だけを見れば十分（それより古い日はどのみち確定済みのため）。
    """
    start = as_of - timedelta(days=lookback_days)
    return awr.gsc_body(start.isoformat(), as_of.isoformat(), ["date"], lookback_days + 1, data_state="all")


def stable_subperiod(start: date, end: date, available_through: date) -> tuple[date, date] | None:
    """要求期間 `start`〜`end` のうち確定済みの部分だけを返す。全部未確定なら None。

    2026-08-26 計測レビュー対応（第2ラウンド・修正2）。
    """
    trimmed_end = min(end, available_through)
    if trimmed_end < start:
        return None
    return start, trimmed_end


def format_period_span(period: dict | None) -> str:
    """`{"start": "...", "end": "..."}` を「2026-08-09〜09-03 の26日」形式にする。作れなければ空文字。

    2026-09-06 表示修正: 増減率がどの期間どうしの比較なのかを、%の隣に必ず書けるようにするための
    共通整形。日数まで書くのは「28日の合計 vs 26日の比較」という取り違えが実際に起きたため
    （日数が違うことが一目で分かれば、同じ誤読はもう起きない）。年をまたぐときだけ終端も
    フル ISO で出す（"09-03" だけだと何年の 9/3 か判断できなくなるため）。
    """
    if not period or not period.get("start") or not period.get("end"):
        return ""
    try:
        s = date.fromisoformat(period["start"])
        e = date.fromisoformat(period["end"])
    except (TypeError, ValueError):
        return ""
    days = (e - s).days + 1
    end_text = e.isoformat() if e.year != s.year else f"{e.month:02d}-{e.day:02d}"
    return f"{s.isoformat()}〜{end_text} の{days}日"


def comparison_span_label(comparison: dict | None) -> str:
    """増減率の行末に併記する「（現在期間 vs 前期間）」。期間が揃わなければ空文字。

    2026-09-06 表示修正: 合計値と増減率が別期間の数字なのに隣り合っていたため誤読が発生した。
    %だけを裸で出さず、必ずこのラベルを付けて「何と何を比べた数字か」を行内で完結させる。
    """
    cur = format_period_span((comparison or {}).get("period"))
    prev = format_period_span((comparison or {}).get("previous_period"))
    if not cur or not prev:
        return ""
    return f"（{cur} vs {prev}）"


def compute_deltas(cur: dict | None, prev: dict | None) -> dict | None:
    """cur/prev（同じキーを持つ totals dict）から {key: {delta, pct}} を作る。片方が無ければ None。"""
    if cur is None or prev is None:
        return None
    out: dict = {}
    for key, cur_val in cur.items():
        delta, pct = awr.wow_delta(cur_val, prev.get(key))
        out[key] = {"delta": delta, "pct": pct}
    return out


def stable_comparison(
    *,
    start: date,
    end: date,
    available_through: date,
    full_period_cur_raw,
    full_period_prev_raw,
    call,
    totals_body_fn,
    parse_fn,
    label_prefix: str,
    safe,
) -> dict:
    """確定分同士の前期間比較を組み立てる（2026-08-26 計測レビュー対応・第2ラウンド修正2）。

    「速報を含む現在期間」と「確定済みの前期間」をそのまま%比較すると、母数の小さいサイトでは
    数件の未反映だけで割合が大きく動く。ここでは要求期間 `start`〜`end` のうち確定済みの部分
    （`stable_subperiod`）だけを使い、同じ長さの直前期間と比較する。

    要求期間が丸ごと確定済み（トリムなし）なら、既に呼び出し側が取得済みの
    `full_period_cur_raw`/`full_period_prev_raw`（fetch_report の raw_totals 相当）をそのまま
    再利用し、無駄な追加リクエストを避ける。トリムが必要なときだけ確定部分に絞った totals を
    新たに取得する。
    """
    stable = stable_subperiod(start, end, available_through)
    if stable is None:
        return {
            "period": None,
            "previous_period": None,
            "totals": None,
            "previous_totals": None,
            "deltas": None,
            "note": "比較保留（確定分が無いため計算できません）",
        }
    stable_start, stable_end = stable
    if stable_end == end:
        # 期間全体が既に確定済み。追加リクエストせず、呼び出し側が既に取得済みの生レスポンスを使う。
        prev_start, prev_end = previous_period(start, end)
        cur_raw, prev_raw = full_period_cur_raw, full_period_prev_raw
        note = None
    else:
        prev_start, prev_end = previous_period(stable_start, stable_end)
        cur_raw = safe(
            call, totals_body_fn(stable_start.isoformat(), stable_end.isoformat()), label=f"{label_prefix}.stable_cur"
        )
        prev_raw = safe(
            call,
            totals_body_fn(prev_start.isoformat(), prev_end.isoformat()),
            label=f"{label_prefix}.stable_prev",
        )
        # 2026-09-06 表示修正: 以前は「比較は確定分同士（〜M/D）」とだけ書いていたため、すぐ上の
        # 「要求期間の合計」とすぐ下の「確定期間どうしの増減率」が別の期間の数字だと読み取れず、
        # 実際に「要求した日数ぶんの合計と、その同じ日数どうしの前期間比」だと誤読する事故が起きた
        # （増減率は速報分を切り落とした、より短い期間どうしの比較。横ばいの指標を「増えた」と読んだ）。
        # 合計側・増減率側それぞれの期間と日数を注記本文に書き切って、取り違えを防ぐ。
        # このリポジトリは public なので、事故時の実数値はここに書かない
        # （docs/ANALYTICS_AGENT_RUNBOOK.md の禁止事項。数字は plan/_local/ 側に置く）。
        note = (
            f"上の合計は {format_period_span({'start': start.isoformat(), 'end': end.isoformat()})}の値、"
            f"下の増減率は確定分同士"
            f"（{format_period_span({'start': stable_start.isoformat(), 'end': stable_end.isoformat()})}"
            f" vs {format_period_span({'start': prev_start.isoformat(), 'end': prev_end.isoformat()})}）"
            f"の比較で、期間が異なります"
        )
    cur_totals = parse_fn(cur_raw) if cur_raw is not None else None
    prev_totals = parse_fn(prev_raw) if prev_raw is not None else None
    return {
        "period": {"start": stable_start.isoformat(), "end": stable_end.isoformat()},
        "previous_period": {"start": prev_start.isoformat(), "end": prev_end.isoformat()},
        "totals": cur_totals,
        "previous_totals": prev_totals,
        "deltas": compute_deltas(cur_totals, prev_totals),
        "note": note,
    }


def position_bucket_counts(rows: list[dict]) -> dict[str, int]:
    """GSC クエリ行のリストを順位帯(1-3/4-10/11-20/21+/unknown)ごとのクエリ数に集計する。

    2026-08-26 計測レビュー対応（第2ラウンド・修正5）: 欠損・0・非有限の position は
    awr.position_bucket が "unknown" を返す（以前は "1-3" に誤分類されていた）。
    """
    counts = {"1-3": 0, "4-10": 0, "11-20": 0, "21+": 0, "unknown": 0}
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
    raw_prev = None
    if compare:
        ps, pe = previous_period(start, end)
        raw_prev = safe(
            ga4_call, awr.ga4_totals_body(ps.isoformat(), pe.isoformat()), label="ga4.totals.previous"
        )
        ga4_prev_totals = awr.parse_ga4_totals(raw_prev) if raw_prev is not None else None

    # 修正2: 「速報込みの現在期間」と「確定済みの前期間」をそのまま%比較しない。確定分同士の
    # 比較を別途 stable_comparison で計算し、deltas はそちらを使う（totals は速報込みの生値のまま表示）。
    # GA4 の確定境界: today/yesterday は速報（ga4_provisional_flag と同じ規約）なので、
    # 確定は as_of の2日前まで。
    ga4_available_through = as_of - timedelta(days=2)
    ga4_stable = (
        stable_comparison(
            start=start,
            end=end,
            available_through=ga4_available_through,
            full_period_cur_raw=raw_totals,
            full_period_prev_raw=raw_prev,
            call=ga4_call,
            totals_body_fn=awr.ga4_totals_body,
            parse_fn=awr.parse_ga4_totals,
            label_prefix="ga4.totals",
            safe=safe,
        )
        if compare
        else None
    )
    # 修正6: PV(screenPageViews)は8/26に計測定義を変更したため、比較に使う4つの日付
    # （確定分同士の比較期間・前期間）がその日をまたぐ場合は screenPageViews の delta だけ
    # 表示側で N/A にする（他の指標には適用しない）。
    ga4_pv_blocked = False
    if ga4_stable and ga4_stable.get("period") and ga4_stable.get("previous_period"):
        cs = date.fromisoformat(ga4_stable["period"]["start"])
        ce = date.fromisoformat(ga4_stable["period"]["end"])
        ps2 = date.fromisoformat(ga4_stable["previous_period"]["start"])
        pe2 = date.fromisoformat(ga4_stable["previous_period"]["end"])
        ga4_pv_blocked = awr.pv_delta_crosses_boundary(cs, ce, ps2, pe2)

    ga4_section = {
        "requested_period": {"start": s, "end": e},
        "provisional": ga4_provisional_flag(end, as_of),
        "provisional_dates": ga4_provisional_dates(start, end, as_of),
        "totals": ga4_totals,
        "previous": ga4_prev_totals,
        "deltas": ga4_stable["deltas"] if ga4_stable else None,
        "comparison": ga4_stable,
        "pv_delta_blocked_by_epoch_change": ga4_pv_blocked,
        "landing_pages": ga4_landing,
        "channels": ga4_channels,
        "events": ga4_events,
    }

    # ---- GSC（dataState="all" = 速報込み。修正2/analytics_report固有） ----
    raw_gsc_totals = safe(gsc_call, awr.gsc_body(s, e, [], 1, data_state="all"), label="gsc.totals")
    gsc_totals = awr.parse_gsc_totals(raw_gsc_totals) if raw_gsc_totals is not None else None
    # 修正1: 確定日は date dimension 専用のプローブから読む（totals レスポンスの metadata では
    # 公式仕様上ほぼ返らない）。プローブが失敗しても safe() が None を返すので、
    # gsc_availability は従来どおり rule フォールバックする。
    raw_gsc_probe = safe(gsc_call, gsc_freshness_probe_body(as_of), label="gsc.freshness_probe")
    availability = gsc_availability(raw_gsc_probe, as_of)
    available_through = date.fromisoformat(availability["available_through"])
    prov_dates = provisional_dates_in_period(start, end, available_through)

    gsc_queries = [
        {"query": r["key"], "clicks": r["clicks"], "impressions": r["impressions"], "position": r["position"]}
        for r in awr.parse_gsc_rows(safe(gsc_call, awr.gsc_body(s, e, ["query"], 25, data_state="all"), label="gsc.queries"))
    ]
    raw_gsc_pages = safe(gsc_call, awr.gsc_body(s, e, ["page"], 200, data_state="all"), label="gsc.pages")
    gsc_pages = [
        {"page": r["key"], "clicks": r["clicks"], "impressions": r["impressions"]}
        for r in awr.parse_gsc_rows(raw_gsc_pages)
    ]
    gsc_query_page = awr.parse_gsc_query_page_rows(
        safe(gsc_call, awr.gsc_body(s, e, ["query", "page"], 200, data_state="all"), label="gsc.query_page")
    )
    # 修正3: gsc.pages の取得自体が失敗したときは qualified を None にする（parse後は空リストに
    # なるため、raw レスポンスの成否で分岐しないと「取得失敗」が偽の0クリックとして出てしまう）。
    if raw_gsc_pages is not None:
        qualified, page_total = awr.qualified_clicks_total(gsc_pages)
    else:
        qualified, page_total = None, None

    gsc_prev_totals = None
    raw_gsc_prev = None
    if compare:
        ps, pe = previous_period(start, end)
        raw_gsc_prev = safe(
            gsc_call,
            awr.gsc_body(ps.isoformat(), pe.isoformat(), [], 1, data_state="all"),
            label="gsc.totals.previous",
        )
        gsc_prev_totals = awr.parse_gsc_totals(raw_gsc_prev) if raw_gsc_prev is not None else None

    def _gsc_totals_body(bs: str, be: str) -> dict:
        return awr.gsc_body(bs, be, [], 1, data_state="all")

    gsc_stable = (
        stable_comparison(
            start=start,
            end=end,
            available_through=available_through,
            full_period_cur_raw=raw_gsc_totals,
            full_period_prev_raw=raw_gsc_prev,
            call=gsc_call,
            totals_body_fn=_gsc_totals_body,
            parse_fn=awr.parse_gsc_totals,
            label_prefix="gsc.totals",
            safe=safe,
        )
        if compare
        else None
    )

    gsc_section = {
        "requested_period": {"start": s, "end": e},
        "available_through": availability["available_through"],
        "availability_source": availability["source"],
        "provisional": bool(prov_dates),
        "provisional_dates": prov_dates,
        "totals": gsc_totals,
        "previous": gsc_prev_totals,
        "deltas": gsc_stable["deltas"] if gsc_stable else None,
        "comparison": gsc_stable,
        "top_queries": gsc_queries,
        "top_pages": gsc_pages,
        "query_page": gsc_query_page,
        "qualified_clicks": {"qualified": qualified, "total": page_total},
        "position_buckets": position_bucket_counts(gsc_queries),
    }

    # ソースごとの状態: 何かひとつでも取れていれば partial、主要データ(totals)すら
    # 全滅していれば failed、失敗が無ければ ok（scripts/analytics_weekly_report.py と共通実装）。
    ga4_status = awr.compute_source_status(
        failed, "ga4.", got_anything=bool(ga4_landing or ga4_channels or ga4_events or ga4_totals is not None)
    )
    gsc_status = awr.compute_source_status(
        failed, "gsc.", got_anything=bool(gsc_queries or gsc_pages or gsc_totals is not None)
    )

    row_limits = {
        "ga4_landing_pages": 10,
        "ga4_channels": 10,
        "ga4_events": 30,
        "gsc_queries": 25,
        "gsc_pages": 200,
        "gsc_query_page": 200,
        "gsc_freshness_probe_days": 10,
    }

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
        # 2026-08-26 計測レビュー対応（第2ラウンド・修正5）: 出力の解釈に必要なメタデータ。
        # schema_version は破壊的変更時にインクリメントする。
        "meta": {
            "schema_version": 2,
            "timezone": "Asia/Tokyo",
            "period": {"start": s, "end": e},
            "row_limits": row_limits,
            "source_status": {"ga4": ga4_status, "gsc": gsc_status},
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
    # 修正2: deltas は「確定分同士」の比較（fetch_report::stable_comparison）。速報込みの生値
    # は上の totals にそのまま出す一方、判断に使う%はここでは確定分だけを使う。
    comparison = ga4.get("comparison") or {}
    deltas = ga4.get("deltas")
    if comparison.get("note"):
        lines.append(f"  ※ {comparison['note']}")
    if deltas:
        # 2026-09-06 表示修正: %だけを裸で出すと、すぐ上の「要求期間の合計」と同じ期間の比較だと
        # 誤読される（実際に起きた）。増減率の行ごとに実際の比較期間と日数を併記する。
        span = comparison_span_label(comparison)
        for key, label in (
            ("activeUsers", "アクティブユーザー"),
            ("sessions", "セッション"),
            ("screenPageViews", "ページビュー"),
        ):
            # 修正6: PVは8/26に計測定義を変更したため、比較対象がその日をまたぐ場合は
            # screenPageViews の delta だけ比較不可として明示する（他指標には適用しない）。
            if key == "screenPageViews" and ga4.get("pv_delta_blocked_by_epoch_change"):
                lines.append(f"  - 前期間比 {label}: 比較不可（8/26にPV計測定義を変更したため）")
                continue
            d = deltas.get(key)
            if d and d.get("pct") is not None:
                sign = "+" if d["delta"] >= 0 else ""
                lines.append(f"  - 前期間比 {label}: {sign}{d['pct']:.1f}%{span}")
    if ga4.get("landing_pages"):
        lines.append("")
        lines.append("### ランディングページ TOP10（API取得上位10件。全件ではありません）")
        for i, row in enumerate(ga4["landing_pages"][:10], 1):
            lines.append(f"{i}. {row.get('page')} … {_fmt_or_na(row.get('sessions'))}")
    if ga4.get("channels"):
        lines.append("")
        lines.append("### 流入チャネル")
        for row in ga4["channels"]:
            lines.append(f"- {row.get('channel')}: {_fmt_or_na(row.get('sessions'))}")
    if ga4.get("events"):
        # 修正6: report_read（旧名）は表示だけ report_view へ合算する。
        events_display = awr.canonical_events_for_display(ga4["events"])
        shown = [(name, events_display[name]) for name in awr.KNOWN_CUSTOM_EVENTS if name in events_display]
        if shown:
            lines.append("")
            lines.append("### イベント（サイト内アクション）")
            for name, cnt in shown:
                lines.append(f"- {name}: {_fmt_or_na(cnt)}")

    lines.append("")
    gsc = report.get("gsc", {})
    gperiod = gsc.get("requested_period", {})
    lines.append(f"## Search Console（{gperiod.get('start')}〜{gperiod.get('end')}）")
    # 修正1: 確定日の出所（date dimension プローブから読めた"metadata" か、規約フォールバックの
    # "rule" か）を明記する。以前はどちらで求めたか区別できず「確定日を取得した」と誤読されがちだった。
    avail_source = gsc.get("availability_source")
    avail_source_label = {"metadata": "APIメタデータ", "rule": "推定（規約ベース）"}.get(avail_source, avail_source)
    lines.append(f"- 確定済み: 〜{gsc.get('available_through')}（判定方法: {avail_source_label}）")
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
    # 修正2: deltas は「確定分同士」の比較。
    gcomparison = gsc.get("comparison") or {}
    gdeltas = gsc.get("deltas")
    if gcomparison.get("note"):
        lines.append(f"  ※ {gcomparison['note']}")
    if gdeltas:
        # 2026-09-06 表示修正: GA4 側と同じ理由で比較期間を併記する（GA4だけ直してGSCを放置しない）。
        gspan = comparison_span_label(gcomparison)
        for key, label in (("clicks", "クリック"), ("impressions", "表示回数")):
            d = gdeltas.get(key)
            if d and d.get("pct") is not None:
                sign = "+" if d["delta"] >= 0 else ""
                lines.append(f"  - 前期間比 {label}: {sign}{d['pct']:.1f}%{gspan}")
    # 「全クリック」は正確な合計値（totals クエリ由来）を使う。qualified_clicks.total は
    # ページ内訳（rowLimit 200 でキャップ、API が返した上位N行の範囲。全件ではない）の合計で、
    # 長い尾を持つサイトだと totals よりわずかに少なくなりうるため、表示上の分母には使わない
    # （週報 compose_digest と揃えた挙動）。
    # 修正3: gsc.pages 取得自体が失敗すると qualified は None（実際の0件と区別するため）。
    qc = gsc.get("qualified_clicks") or {}
    lines.append(
        f"- 有効クリック: {_fmt_or_na(qc.get('qualified'))}（全クリック {_fmt_or_na((gtotals or {}).get('clicks'))}）"
    )
    buckets = gsc.get("position_buckets") or {}
    if buckets:
        # 修正5: これは全クエリではなく「クリック上位25検索語」内の非加重件数（gsc.queries の
        # rowLimit=25 が母集団）。position が欠損/0/非有限だった行は unknown。
        lines.append(
            "- 順位帯（クリック上位25検索語の集計）: "
            f"1-3={buckets.get('1-3', 0)} / 4-10={buckets.get('4-10', 0)} / "
            f"11-20={buckets.get('11-20', 0)} / 21+={buckets.get('21+', 0)} / "
            f"unknown={buckets.get('unknown', 0)}"
        )
    top_queries = gsc.get("top_queries") or []
    if top_queries:
        lines.append("")
        lines.append("### 検索クエリ TOP10（API取得上位25件のうち上位10件。全件ではありません）")
        brand_labels = {"site": "指名(サイト)", "chain": "指名(チェーン)", "generic": "一般"}
        for i, row in enumerate(top_queries[:10], 1):
            brand_kind = awr.classify_query_brand(row.get("query") or "")
            branded = brand_labels[brand_kind]
            lines.append(f"{i}. 「{row.get('query')}」（{branded}） … {_fmt_or_na(row.get('clicks'))}クリック")
    query_page = gsc.get("query_page") or []
    if query_page:
        top_qp = sorted(query_page, key=lambda r: r.get("clicks") or 0, reverse=True)[:5]
        lines.append("")
        lines.append("### 検索語→ページ TOP5（API取得上位行からの抜粋。全件ではありません）")
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
