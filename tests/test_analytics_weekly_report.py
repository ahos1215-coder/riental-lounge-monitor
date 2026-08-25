"""Unit tests for scripts/analytics_weekly_report.py.

ネットワークには一切アクセスしない。GA4/GSC 呼び出しは fake を注入し、純粋関数
（週の窓計算・前週比・ダイジェスト組み立て・レスポンス parse）と、認証情報が無い
ときの graceful no-op（exit 0 + 案内メッセージ）を検証する。
"""

from __future__ import annotations

from datetime import datetime

import pytest

import scripts.analytics_weekly_report as awr

JST = awr.JST


# --------------------------------------------------------------------------
# 週の窓計算（月〜日, JST）
# --------------------------------------------------------------------------


def test_last_full_week_from_monday():
    # 2026-07-13 は月曜（09:00 実行想定）。対象は直前の月〜日。
    now = datetime(2026, 7, 13, 9, 0, tzinfo=JST)
    w = awr.last_full_week(now)
    assert w.cur_start.isoformat() == "2026-07-06"
    assert w.cur_end.isoformat() == "2026-07-12"
    assert w.prev_start.isoformat() == "2026-06-29"
    assert w.prev_end.isoformat() == "2026-07-05"


def test_last_full_week_from_midweek_is_same_completed_week():
    # 週の途中（水曜）に走らせても、対象は「今週の月曜より前の完結した月〜日」。
    now = datetime(2026, 7, 15, 3, 0, tzinfo=JST)
    w = awr.last_full_week(now)
    assert w.cur_start.isoformat() == "2026-07-06"
    assert w.cur_end.isoformat() == "2026-07-12"


def test_last_full_week_from_sunday():
    # 日曜（まだ今週の月曜を跨いでいない）→ 対象は前々週始まりの直近完結週。
    now = datetime(2026, 7, 12, 23, 0, tzinfo=JST)
    w = awr.last_full_week(now)
    assert w.cur_start.isoformat() == "2026-06-29"
    assert w.cur_end.isoformat() == "2026-07-05"


# --------------------------------------------------------------------------
# 前週比の計算・整形
# --------------------------------------------------------------------------


def test_wow_delta_positive_negative_zero_baseline():
    assert awr.wow_delta(120, 100) == (20.0, pytest.approx(20.0))
    d, pct = awr.wow_delta(80, 100)
    assert d == pytest.approx(-20.0)
    assert pct == pytest.approx(-20.0)
    # 前週が 0 → 率は算出不能(None)
    d0, pct0 = awr.wow_delta(50, 0)
    assert d0 == 50.0
    assert pct0 is None


def test_wow_str_formatting():
    assert awr.wow_str(1234, 1100) == "+12.2% ↑"
    assert awr.wow_str(80, 100) == "-20.0% ↓"
    assert awr.wow_str(100, 100) == "+0.0% →"
    assert awr.wow_str(50, 0) == "新規"
    assert awr.wow_str(0, 0) == "±0"


def test_top_growth_picks_biggest_riser():
    cur = [{"path": "/a", "views": 800}, {"path": "/b", "views": 300}]
    prev = [{"path": "/a", "views": 680}, {"path": "/b", "views": 250}]
    item, delta = awr.top_growth(cur, prev, "path", "views")
    assert item["path"] == "/a"
    assert delta == pytest.approx(120.0)


def test_top_growth_empty_returns_none():
    assert awr.top_growth([], [], "path", "views") is None


def test_top_growth_no_positive_growth_returns_none():
    # 2026-08-26 計測レビュー対応（修正1b）: 全て横ばい/減少なら「伸びた」とは言わず None。
    cur = [{"path": "/a", "views": 680}, {"path": "/b", "views": 250}]
    prev = [{"path": "/a", "views": 800}, {"path": "/b", "views": 300}]
    assert awr.top_growth(cur, prev, "path", "views") is None
    # +0（完全な横ばい）も「伸びた」扱いにしない。
    cur0 = [{"path": "/a", "views": 800}]
    prev0 = [{"path": "/a", "views": 800}]
    assert awr.top_growth(cur0, prev0, "path", "views") is None


# --------------------------------------------------------------------------
# 確定週の選定（GSC 用の last_confirmed_week）
# --------------------------------------------------------------------------


def test_last_confirmed_week_monday_run_goes_back_two_weeks():
    # 月曜09:00実行 → last_full_week の週(7/6-7/12、実行日との差1日)はまだ未確定 →
    # 1週遡った前々週(6/29-7/5、差8日)が確定週になる。
    now = datetime(2026, 7, 13, 9, 0, tzinfo=JST)
    w = awr.last_confirmed_week(now)
    assert w.cur_start.isoformat() == "2026-06-29"
    assert w.cur_end.isoformat() == "2026-07-05"
    # 前週比の相方も同じだけ遡っている（確定週同士の比較）。
    assert w.prev_start.isoformat() == "2026-06-22"
    assert w.prev_end.isoformat() == "2026-06-28"


def test_last_confirmed_week_when_already_confirmed_matches_last_full_week():
    # 実行日が週末寄りなら last_full_week がそのまま確定週（遡らない）。
    now = datetime(2026, 7, 17, 9, 0, tzinfo=JST)  # 金曜、直近完結週の終端(7/12)との差は5日
    w_full = awr.last_full_week(now)
    w_confirmed = awr.last_confirmed_week(now)
    assert w_confirmed == w_full


# --------------------------------------------------------------------------
# リクエストボディ生成
# --------------------------------------------------------------------------


def test_ga4_totals_body_shape():
    body = awr.ga4_totals_body("2026-07-06", "2026-07-12")
    assert body["dateRanges"] == [{"startDate": "2026-07-06", "endDate": "2026-07-12"}]
    assert {m["name"] for m in body["metrics"]} == {"activeUsers", "sessions", "screenPageViews"}
    assert "dimensions" not in body


def test_ga4_dim_body_shape():
    body = awr.ga4_dim_body("2026-07-06", "2026-07-12", "pagePath", "screenPageViews", 10)
    assert body["dimensions"] == [{"name": "pagePath"}]
    assert body["metrics"] == [{"name": "screenPageViews"}]
    assert body["limit"] == 10
    assert body["orderBys"][0]["metric"]["metricName"] == "screenPageViews"
    assert body["orderBys"][0]["desc"] is True


def test_gsc_body_totals_vs_dimensioned():
    totals = awr.gsc_body("2026-07-06", "2026-07-12", [], 1)
    assert "dimensions" not in totals
    assert totals["rowLimit"] == 1
    q = awr.gsc_body("2026-07-06", "2026-07-12", ["query"], 10)
    assert q["dimensions"] == ["query"]


# --------------------------------------------------------------------------
# レスポンス parse
# --------------------------------------------------------------------------


def test_parse_ga4_totals():
    resp = {
        "metricHeaders": [{"name": "activeUsers"}, {"name": "sessions"}, {"name": "screenPageViews"}],
        "rows": [{"metricValues": [{"value": "1234"}, {"value": "1500"}, {"value": "4200"}]}],
    }
    out = awr.parse_ga4_totals(resp)
    assert out == {"activeUsers": 1234.0, "sessions": 1500.0, "screenPageViews": 4200.0}


def test_parse_ga4_totals_no_rows_is_zero():
    resp = {"metricHeaders": [{"name": "sessions"}], "rows": []}
    assert awr.parse_ga4_totals(resp) == {"sessions": 0.0}


def test_parse_ga4_rows():
    resp = {
        "rows": [
            {"dimensionValues": [{"value": "/store/shibuya"}], "metricValues": [{"value": "800"}]},
            {"dimensionValues": [{"value": "/store/shinjuku"}], "metricValues": [{"value": "500"}]},
        ]
    }
    assert awr.parse_ga4_rows(resp) == [("/store/shibuya", 800.0), ("/store/shinjuku", 500.0)]


def test_parse_gsc_totals_and_rows():
    totals = awr.parse_gsc_totals(
        {"rows": [{"clicks": 320, "impressions": 15000, "ctr": 0.0213, "position": 12.4}]}
    )
    assert totals["clicks"] == 320.0
    assert totals["impressions"] == 15000.0
    empty = awr.parse_gsc_totals({"rows": []})
    assert empty == {"clicks": 0.0, "impressions": 0.0, "ctr": 0.0, "position": 0.0}
    rows = awr.parse_gsc_rows({"rows": [{"keys": ["渋谷 相席"], "clicks": 40, "impressions": 900}]})
    assert rows[0]["key"] == "渋谷 相席"
    assert rows[0]["clicks"] == 40.0


# --------------------------------------------------------------------------
# fetch_metrics（fake 注入・部分失敗の握りつぶし）
# --------------------------------------------------------------------------


def _fake_ga4(body: dict) -> dict:
    dims = body.get("dimensions")
    if not dims:
        return {
            "metricHeaders": [{"name": "activeUsers"}, {"name": "sessions"}, {"name": "screenPageViews"}],
            "rows": [{"metricValues": [{"value": "1234"}, {"value": "1500"}, {"value": "4200"}]}],
        }
    dim = dims[0]["name"]
    if dim == "pagePath":
        return {"rows": [{"dimensionValues": [{"value": "/store/shibuya"}], "metricValues": [{"value": "800"}]}]}
    if dim == "eventName":
        return {"rows": [{"dimensionValues": [{"value": "store_view"}], "metricValues": [{"value": "900"}]}]}
    if dim == "sessionDefaultChannelGroup":
        return {"rows": [{"dimensionValues": [{"value": "Organic Search"}], "metricValues": [{"value": "700"}]}]}
    return {"rows": []}


def _fake_gsc(body: dict) -> dict:
    dims = body.get("dimensions")
    if not dims:
        return {"rows": [{"clicks": 320, "impressions": 15000, "ctr": 0.0213, "position": 12.4}]}
    if dims == ["query"]:
        return {"rows": [{"keys": ["渋谷 相席"], "clicks": 40, "impressions": 900}]}
    if dims == ["page"]:
        return {"rows": [{"keys": ["https://www.meguribi.jp/store/shibuya"], "clicks": 50, "impressions": 1200}]}
    if dims == ["query", "page"]:
        return {
            "rows": [
                {
                    "keys": ["渋谷 相席", "https://www.meguribi.jp/store/shibuya"],
                    "clicks": 40,
                    "impressions": 900,
                }
            ]
        }
    return {"rows": []}


def test_fetch_metrics_assembles_structure():
    ga4_weeks = awr.last_full_week(datetime(2026, 7, 13, 9, 0, tzinfo=JST))
    gsc_weeks = awr.last_confirmed_week(datetime(2026, 7, 13, 9, 0, tzinfo=JST))
    m = awr.fetch_metrics(ga4_weeks, gsc_weeks, _fake_ga4, _fake_gsc)
    assert m["ga4"]["totals"]["cur"]["activeUsers"] == 1234.0
    assert m["ga4"]["top_pages"]["cur"][0]["path"] == "/store/shibuya"
    assert m["ga4"]["events"]["cur"]["store_view"] == 900.0
    assert m["ga4"]["channels"]["cur"][0]["channel"] == "Organic Search"
    assert m["gsc"]["totals"]["cur"]["clicks"] == 320.0
    assert m["gsc"]["top_queries"]["cur"][0]["query"] == "渋谷 相席"
    # 修正2: query×page の生データと、有効検索クリック(qualified_clicks)。
    assert m["gsc"]["query_page"]["cur"][0]["query"] == "渋谷 相席"
    assert m["gsc"]["query_page"]["cur"][0]["page"] == "https://www.meguribi.jp/store/shibuya"
    assert m["gsc"]["qualified_clicks"]["cur"] == 50.0  # /store/shibuya は "store" カテゴリ=有効
    # 週の窓は GA4/GSC で別々に持つ（修正1d）。
    assert m["weeks"]["ga4"]["cur"]["start"] == ga4_weeks.cur_start.isoformat()
    assert m["weeks"]["gsc"]["cur"]["start"] == gsc_weeks.cur_start.isoformat()
    assert m["warnings"] == []
    assert m["data_quality"]["failed"] == []


def test_fetch_metrics_tolerates_partial_failure():
    def flaky_ga4(body: dict) -> dict:
        if body.get("dimensions") and body["dimensions"][0]["name"] == "sessionDefaultChannelGroup":
            raise RuntimeError("boom")
        return _fake_ga4(body)

    now = datetime(2026, 7, 13, 9, 0, tzinfo=JST)
    m = awr.fetch_metrics(awr.last_full_week(now), awr.last_confirmed_week(now), flaky_ga4, _fake_gsc)
    # 落ちたのは channels だけ。他は揃い、warnings と data_quality.failed の両方に記録が残る。
    assert m["ga4"]["channels"]["cur"] == []
    assert any("ga4.channels.cur" in w for w in m["warnings"])
    assert m["data_quality"]["failed"] == ["ga4.channels.cur"]
    assert m["ga4"]["totals"]["cur"]["activeUsers"] == 1234.0
    # 部分データでも digest は組める。
    digest = awr.compose_digest(m)
    assert "一部データの取得に失敗" in digest
    assert "ga4.channels.cur" in digest  # どのソースが失敗したかが警告に含まれる（修正1c）。


def test_fetch_metrics_totals_failure_shows_na_not_zero():
    # 2026-08-26 計測レビュー対応（修正1c）: 総数クエリ自体が落ちたら fmt_int(None)="0" の
    # 偽ゼロではなく「取得失敗」と表示する。
    def broken_ga4(body: dict) -> dict:
        if not body.get("dimensions"):
            raise RuntimeError("network down")
        return _fake_ga4(body)

    now = datetime(2026, 7, 13, 9, 0, tzinfo=JST)
    m = awr.fetch_metrics(awr.last_full_week(now), awr.last_confirmed_week(now), broken_ga4, _fake_gsc)
    assert m["ga4"]["totals"]["cur"] is None
    assert "ga4.totals.cur" in m["data_quality"]["failed"]
    digest = awr.compose_digest(m)
    assert "アクティブユーザー: 取得失敗" in digest
    assert "前週比 取得失敗" in digest
    # 実際にゼロ件だった別指標(=正常応答で0)は、これとは別に "0" のまま出ることを想定
    # （このテストでは失敗した側だけを確認する）。


# --------------------------------------------------------------------------
# ダイジェスト組み立て（固定フィクスチャ → 期待する日本語スニペット）
# --------------------------------------------------------------------------


def _fixture_metrics() -> dict:
    return {
        "generated_at_utc": "2026-07-13T00:00:00+00:00",
        "weeks": {
            "ga4": {
                "cur": {"start": "2026-07-06", "end": "2026-07-12"},
                "prev": {"start": "2026-06-29", "end": "2026-07-05"},
            },
            # GSC は確定に数日かかるため GA4 より2週分過去（修正1d）。
            "gsc": {
                "cur": {"start": "2026-06-29", "end": "2026-07-05"},
                "prev": {"start": "2026-06-22", "end": "2026-06-28"},
            },
        },
        "ga4": {
            "totals": {
                "cur": {"activeUsers": 1234, "sessions": 1500, "screenPageViews": 4200},
                "prev": {"activeUsers": 1100, "sessions": 1400, "screenPageViews": 3900},
            },
            "top_pages": {
                "cur": [
                    {"path": "/store/shibuya", "views": 800},
                    {"path": "/store/shinjuku", "views": 500},
                    {"path": "/reports", "views": 300},
                ],
                "prev": [
                    {"path": "/store/shibuya", "views": 680},
                    {"path": "/store/shinjuku", "views": 520},
                    {"path": "/reports", "views": 250},
                ],
            },
            "events": {
                "cur": {"page_view": 5000, "store_view": 900, "report_read": 300, "favorite_add": 40},
                "prev": {"page_view": 4800, "store_view": 855, "report_read": 280, "favorite_add": 55},
            },
            "channels": {"cur": [{"channel": "Organic Search", "sessions": 700}, {"channel": "Direct", "sessions": 500}]},
        },
        "gsc": {
            "totals": {
                "cur": {"clicks": 320, "impressions": 15000, "ctr": 0.0213, "position": 12.4},
                "prev": {"clicks": 280, "impressions": 14000, "ctr": 0.02, "position": 13.1},
            },
            "top_queries": {
                "cur": [{"query": "渋谷 相席", "clicks": 40, "impressions": 900}],
                "prev": [{"query": "渋谷 相席", "clicks": 25, "impressions": 800}],
            },
            "top_pages": {"cur": [{"page": "https://www.meguribi.jp/store/shibuya", "clicks": 50, "impressions": 1200}]},
            "query_page": {
                "cur": [
                    {
                        "query": "渋谷 相席",
                        "page": "https://www.meguribi.jp/store/shibuya",
                        "clicks": 40,
                        "impressions": 900,
                    },
                    {
                        "query": "新宿 混雑",
                        "page": "https://www.meguribi.jp/store/shinjuku",
                        "clicks": 10,
                        "impressions": 300,
                    },
                ]
            },
            "qualified_clicks": {"cur": 50.0, "page_total": 50.0},
        },
        "warnings": [],
        "data_quality": {"failed": []},
    }


def test_compose_digest_snippets_and_length():
    digest = awr.compose_digest(_fixture_metrics())
    assert "【めぐりび 週次アナリティクス】" in digest
    assert "対象: 2026-07-06〜2026-07-12" in digest
    assert "アクティブユーザー: 1,234（前週比 +12.2% ↑）" in digest
    assert "ページビュー: 4,200" in digest
    assert "クリック: 320（前週比 +14.3% ↑）" in digest
    assert "最も伸びたページ: /store/shibuya（+120PV）" in digest
    assert "最も伸びた検索クエリ: 「渋谷 相席」（+15クリック）" in digest
    assert "store_view: 900" in digest
    # 自動収集イベント(page_view)はカスタムイベント一覧に出さない。
    assert "・page_view:" not in digest
    # 修正1d: GSC確定週は GA4 の週とは別行で、日付表記も明記する。
    assert "GSC確定週: 6/29〜7/5（検索データは数日遅れで確定するため、GA4の週とはズレます）" in digest
    # 修正2: 有効検索クリックと、検索語→ページ TOP3。
    assert "有効クリック: 50（全クリック 320）" in digest
    assert "「渋谷 相席」→ /store/shibuya（40クリック）" in digest
    # LINE 向けに 2000 字上限。
    assert len(digest) <= awr.DIGEST_MAX_CHARS


def test_compose_digest_handles_empty_gsc_gracefully():
    m = _fixture_metrics()
    m["gsc"]["totals"]["cur"] = {"clicks": 0.0, "impressions": 0.0, "ctr": 0.0, "position": 0.0}
    m["gsc"]["totals"]["prev"] = {"clicks": 0.0, "impressions": 0.0, "ctr": 0.0, "position": 0.0}
    m["gsc"]["top_queries"] = {"cur": [], "prev": []}
    digest = awr.compose_digest(m)
    assert "クリック: 0（前週比 ±0）" in digest
    # GA4 側のハイライトは残る（ページの伸びは出せる）。
    assert "最も伸びたページ: /store/shibuya" in digest


# --------------------------------------------------------------------------
# ページ分類・指名判定・順位帯・有効検索クリック（修正2）
# --------------------------------------------------------------------------


def test_classify_page_path_categories():
    assert awr.classify_page_path("https://www.meguribi.jp/") == "home"
    assert awr.classify_page_path("/") == "home"
    assert awr.classify_page_path("") == "home"
    assert awr.classify_page_path("https://www.meguribi.jp/store/shibuya") == "store"
    assert awr.classify_page_path("/store/shibuya") == "store"
    assert awr.classify_page_path("/area/tokyo") == "area"
    assert awr.classify_page_path("/stores") == "stores"
    assert awr.classify_page_path("/blog/some-post") == "blog"
    assert awr.classify_page_path("/reports/daily/shibuya") == "report"
    assert awr.classify_page_path("/reports/weekly/shibuya") == "report"
    assert awr.classify_page_path("/mypage") == "other"


def test_classify_page_path_closed_store_is_not_store():
    # frontend/src/proxy.ts::CLOSED_STORE_SLUGS と同じ集合。閉店店舗は "store" と混ぜない。
    assert awr.classify_page_path("/store/sapporo_ag") == "closed"
    assert awr.classify_page_path("https://www.meguribi.jp/store/ay_niigata") == "closed"
    # 大文字表記や URL エンコードでも判定が揺れない。
    assert awr.classify_page_path("/store/SAPPORO_AG") == "closed"


def test_is_branded_query():
    assert awr.is_branded_query("めぐりび 渋谷") is True
    assert awr.is_branded_query("Meguribi review") is True
    assert awr.is_branded_query("MEGURIBI") is True
    assert awr.is_branded_query("megribi") is True  # ブランド表記 MEGRIBI 由来の綴り（実CLIで一般扱いになっていた実例）
    assert awr.is_branded_query("渋谷 相席ラウンジ") is False
    assert awr.is_branded_query("") is False


def test_position_bucket():
    assert awr.position_bucket(1.0) == "1-3"
    assert awr.position_bucket(3.0) == "1-3"
    assert awr.position_bucket(3.1) == "4-10"
    assert awr.position_bucket(10.0) == "4-10"
    assert awr.position_bucket(10.5) == "11-20"
    assert awr.position_bucket(20.0) == "11-20"
    assert awr.position_bucket(20.1) == "21+"
    assert awr.position_bucket(45.0) == "21+"


def test_qualified_clicks_total_excludes_report_and_closed():
    rows = [
        {"page": "https://www.meguribi.jp/store/shibuya", "clicks": 40},
        {"page": "https://www.meguribi.jp/reports/daily/shibuya", "clicks": 15},  # noindex → 対象外
        {"page": "https://www.meguribi.jp/store/sapporo_ag", "clicks": 5},  # 閉店 → 対象外
        {"page": "https://www.meguribi.jp/blog/some-post", "clicks": 8},
        {"page": "https://www.meguribi.jp/mypage", "clicks": 2},  # other → 対象外
    ]
    qualified, total = awr.qualified_clicks_total(rows)
    assert qualified == 48.0  # shibuya(40) + blog(8)
    assert total == 70.0


def test_parse_gsc_query_page_rows():
    resp = {
        "rows": [
            {
                "keys": ["渋谷 相席", "https://www.meguribi.jp/store/shibuya"],
                "clicks": 12,
                "impressions": 200,
                "ctr": 0.06,
                "position": 4.2,
            }
        ]
    }
    rows = awr.parse_gsc_query_page_rows(resp)
    assert rows[0]["query"] == "渋谷 相席"
    assert rows[0]["page"] == "https://www.meguribi.jp/store/shibuya"
    assert rows[0]["clicks"] == 12.0
    assert awr.parse_gsc_query_page_rows({}) == []
    assert awr.parse_gsc_query_page_rows(None) == []


def test_gsc_body_accepts_data_state():
    # 既定(省略時)は dataState を付けない(=GSC既定の "final")。CLI(analytics_report.py)は
    # "all" を明示できる必要がある。
    default_body = awr.gsc_body("2026-07-06", "2026-07-12", [], 1)
    assert "dataState" not in default_body
    body = awr.gsc_body("2026-07-06", "2026-07-12", [], 1, data_state="all")
    assert body["dataState"] == "all"


# --------------------------------------------------------------------------
# 認証情報が無いとき: 案内を出して exit 0（--dry-run でも同じ）
# --------------------------------------------------------------------------


def test_no_credentials_prints_guide_and_exits_zero(monkeypatch, tmp_path, capsys):
    # GA4_PROPERTY_ID を空に固定し、鍵ファイルは存在しないパスを指す。
    monkeypatch.setenv("GA4_PROPERTY_ID", "")
    monkeypatch.setenv("GA_SERVICE_ACCOUNT_JSON", str(tmp_path / "does-not-exist.json"))
    rc = awr.main(["--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "docs/ANALYTICS_SETUP.md" in out
    assert "未セットアップ" in out


def test_credentials_present_helper(tmp_path):
    key = tmp_path / "ga.json"
    key.write_text("{}", encoding="utf-8")
    assert awr._credentials_present("493123456", key) is True
    assert awr._credentials_present("", key) is False
    assert awr._credentials_present("493123456", tmp_path / "missing.json") is False
