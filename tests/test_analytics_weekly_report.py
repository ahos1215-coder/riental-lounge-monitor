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
    return {"rows": [{"keys": ["https://www.meguribi.jp/store/shibuya"], "clicks": 50, "impressions": 1200}]}


def test_fetch_metrics_assembles_structure():
    weeks = awr.last_full_week(datetime(2026, 7, 13, 9, 0, tzinfo=JST))
    m = awr.fetch_metrics(weeks, _fake_ga4, _fake_gsc)
    assert m["ga4"]["totals"]["cur"]["activeUsers"] == 1234.0
    assert m["ga4"]["top_pages"]["cur"][0]["path"] == "/store/shibuya"
    assert m["ga4"]["events"]["cur"]["store_view"] == 900.0
    assert m["ga4"]["channels"]["cur"][0]["channel"] == "Organic Search"
    assert m["gsc"]["totals"]["cur"]["clicks"] == 320.0
    assert m["gsc"]["top_queries"]["cur"][0]["query"] == "渋谷 相席"
    assert m["warnings"] == []


def test_fetch_metrics_tolerates_partial_failure():
    def flaky_ga4(body: dict) -> dict:
        if body.get("dimensions") and body["dimensions"][0]["name"] == "sessionDefaultChannelGroup":
            raise RuntimeError("boom")
        return _fake_ga4(body)

    weeks = awr.last_full_week(datetime(2026, 7, 13, 9, 0, tzinfo=JST))
    m = awr.fetch_metrics(weeks, flaky_ga4, _fake_gsc)
    # 落ちたのは channels だけ。他は揃い、warnings に記録が残る。
    assert m["ga4"]["channels"]["cur"] == []
    assert any("ga4.channels.cur" in w for w in m["warnings"])
    assert m["ga4"]["totals"]["cur"]["activeUsers"] == 1234.0
    # 部分データでも digest は組める。
    digest = awr.compose_digest(m)
    assert "一部データの取得に失敗" in digest


# --------------------------------------------------------------------------
# ダイジェスト組み立て（固定フィクスチャ → 期待する日本語スニペット）
# --------------------------------------------------------------------------


def _fixture_metrics() -> dict:
    return {
        "generated_at_utc": "2026-07-13T00:00:00+00:00",
        "weeks": {
            "cur": {"start": "2026-07-06", "end": "2026-07-12"},
            "prev": {"start": "2026-06-29", "end": "2026-07-05"},
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
        },
        "warnings": [],
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
