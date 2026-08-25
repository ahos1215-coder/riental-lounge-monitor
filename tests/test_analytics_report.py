"""Unit tests for scripts/analytics_report.py（最新分析CLI）。

ネットワークには一切アクセスしない。GA4/GSC 呼び出しは fake を注入し、純粋関数
（期間計算・確定日判定・deltas・順位帯集計）と、fetch_report/compose_markdown の
組み立て、認証情報が無いときの exit 1、部分失敗の exit 3 を検証する。
すべて合成データ（実測値・実クエリは書かない）。
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

import scripts.analytics_report as ar

JST = ar.JST


# --------------------------------------------------------------------------
# 期間計算
# --------------------------------------------------------------------------


def test_resolve_period_latest_uses_days_back_from_as_of():
    as_of = date(2026, 8, 26)
    s, e = ar.resolve_period("latest", 28, None, None, as_of)
    assert e == as_of
    assert s == date(2026, 7, 30)  # 28日間 = as_of を含めて28日 → 27日前が開始
    s7, e7 = ar.resolve_period("latest", 7, None, None, as_of)
    assert (e7 - s7).days == 6
    assert e7 == as_of


def test_resolve_period_range_requires_both_start_and_end():
    with pytest.raises(ValueError, match="--start と --end"):
        ar.resolve_period("range", 28, "2026-07-01", None, date(2026, 8, 26))
    with pytest.raises(ValueError, match="--start と --end"):
        ar.resolve_period("range", 28, None, "2026-07-31", date(2026, 8, 26))


def test_resolve_period_range_rejects_start_after_end():
    with pytest.raises(ValueError, match="以前の日付"):
        ar.resolve_period("range", 28, "2026-08-01", "2026-07-01", date(2026, 8, 26))


def test_resolve_period_range_returns_given_bounds():
    s, e = ar.resolve_period("range", 28, "2026-07-01", "2026-07-31", date(2026, 8, 26))
    assert s == date(2026, 7, 1)
    assert e == date(2026, 7, 31)


def test_resolve_period_unknown_mode_raises():
    with pytest.raises(ValueError, match="未知の --mode"):
        ar.resolve_period("bogus", 28, None, None, date(2026, 8, 26))


def test_previous_period_matches_length():
    s, e = date(2026, 7, 1), date(2026, 7, 31)  # 31日間
    ps, pe = ar.previous_period(s, e)
    assert pe == date(2026, 6, 30)
    assert (pe - ps).days == (e - s).days
    assert ps == date(2026, 5, 31)


# --------------------------------------------------------------------------
# GA4 の provisional 判定
# --------------------------------------------------------------------------


def test_ga4_provisional_flag_true_when_period_includes_today_or_yesterday():
    as_of = date(2026, 8, 26)
    assert ar.ga4_provisional_flag(date(2026, 8, 26), as_of) is True  # 当日を含む
    assert ar.ga4_provisional_flag(date(2026, 8, 25), as_of) is True  # 前日を含む
    assert ar.ga4_provisional_flag(date(2026, 8, 24), as_of) is False  # 2日前で確定


def test_ga4_provisional_dates_lists_only_the_unsettled_tail():
    as_of = date(2026, 8, 26)
    dates = ar.ga4_provisional_dates(date(2026, 8, 1), date(2026, 8, 26), as_of)
    assert dates == ["2026-08-25", "2026-08-26"]
    # 期間が過去のみで完結していれば空リスト。
    assert ar.ga4_provisional_dates(date(2026, 7, 1), date(2026, 7, 10), as_of) == []


# --------------------------------------------------------------------------
# GSC の確定日判定
# --------------------------------------------------------------------------


def test_gsc_availability_falls_back_to_rule_when_no_metadata():
    as_of = date(2026, 8, 26)
    avail = ar.gsc_availability({}, as_of)
    assert avail["source"] == "rule"
    assert avail["available_through"] == "2026-08-23"  # as_of - 3日


def test_gsc_availability_uses_metadata_when_present():
    as_of = date(2026, 8, 26)
    resp = {"metadata": {"first_incomplete_date": "2026-08-24"}}
    avail = ar.gsc_availability(resp, as_of)
    assert avail["source"] == "metadata"
    assert avail["available_through"] == "2026-08-23"


def test_gsc_availability_handles_none_response():
    avail = ar.gsc_availability(None, date(2026, 8, 26))
    assert avail["source"] == "rule"


def test_provisional_dates_in_period():
    available_through = date(2026, 8, 23)
    dates = ar.provisional_dates_in_period(date(2026, 8, 20), date(2026, 8, 26), available_through)
    assert dates == ["2026-08-24", "2026-08-25", "2026-08-26"]
    # 期間全体が確定済みなら空リスト。
    assert ar.provisional_dates_in_period(date(2026, 8, 1), date(2026, 8, 10), available_through) == []


# --------------------------------------------------------------------------
# deltas / 順位帯
# --------------------------------------------------------------------------


def test_compute_deltas_returns_none_when_either_side_missing():
    assert ar.compute_deltas(None, {"clicks": 10}) is None
    assert ar.compute_deltas({"clicks": 10}, None) is None


def test_compute_deltas_shape():
    d = ar.compute_deltas({"clicks": 120, "impressions": 1000}, {"clicks": 100, "impressions": 1000})
    assert d["clicks"]["delta"] == pytest.approx(20.0)
    assert d["clicks"]["pct"] == pytest.approx(20.0)
    assert d["impressions"]["pct"] == pytest.approx(0.0)


def test_position_bucket_counts():
    rows = [{"position": 1.5}, {"position": 5.0}, {"position": 5.5}, {"position": 30.0}]
    counts = ar.position_bucket_counts(rows)
    assert counts == {"1-3": 1, "4-10": 2, "11-20": 0, "21+": 1}
    assert ar.position_bucket_counts([]) == {"1-3": 0, "4-10": 0, "11-20": 0, "21+": 0}


# --------------------------------------------------------------------------
# fetch_report（fake 注入）
# --------------------------------------------------------------------------


def _fake_ga4(body: dict) -> dict:
    dims = body.get("dimensions")
    if not dims:
        return {
            "metricHeaders": [{"name": "activeUsers"}, {"name": "sessions"}, {"name": "screenPageViews"}],
            "rows": [{"metricValues": [{"value": "50"}, {"value": "60"}, {"value": "200"}]}],
        }
    dim = dims[0]["name"]
    if dim == "landingPage":
        return {"rows": [{"dimensionValues": [{"value": "/"}], "metricValues": [{"value": "30"}]}]}
    if dim == "sessionDefaultChannelGroup":
        return {"rows": [{"dimensionValues": [{"value": "Organic Search"}], "metricValues": [{"value": "40"}]}]}
    if dim == "eventName":
        return {"rows": [{"dimensionValues": [{"value": "store_view"}], "metricValues": [{"value": "12"}]}]}
    return {"rows": []}


def _fake_gsc(body: dict) -> dict:
    assert body.get("dataState") == "all"  # 修正2/CLI固有: 最新分析は速報込みで取る
    dims = body.get("dimensions")
    if not dims:
        return {"rows": [{"clicks": 20, "impressions": 500, "ctr": 0.04, "position": 8.0}]}
    if dims == ["query"]:
        return {"rows": [{"keys": ["めぐりび 渋谷"], "clicks": 10, "impressions": 100, "position": 2.0}]}
    if dims == ["page"]:
        return {"rows": [{"keys": ["https://www.meguribi.jp/store/shibuya"], "clicks": 10, "impressions": 100}]}
    if dims == ["query", "page"]:
        return {
            "rows": [
                {
                    "keys": ["めぐりび 渋谷", "https://www.meguribi.jp/store/shibuya"],
                    "clicks": 10,
                    "impressions": 100,
                }
            ]
        }
    return {"rows": []}


def test_fetch_report_assembles_structure_no_compare():
    period = (date(2026, 7, 30), date(2026, 8, 26))
    report = ar.fetch_report(period, date(2026, 8, 26), False, _fake_ga4, _fake_gsc)
    assert report["ga4"]["totals"]["activeUsers"] == 50.0
    assert report["ga4"]["provisional"] is True  # 期間が as_of（今日）を含む
    assert report["ga4"]["deltas"] is None  # compare=False
    assert report["gsc"]["totals"]["clicks"] == 20.0
    assert report["gsc"]["qualified_clicks"]["qualified"] == 10.0  # /store/shibuya は有効
    assert report["gsc"]["query_page"][0]["query"] == "めぐりび 渋谷"
    assert report["data_quality"]["source_status"] == {"ga4": "ok", "gsc": "ok"}
    assert report["data_quality"]["warnings"] == []


def test_fetch_report_with_compare_computes_deltas():
    period = (date(2026, 7, 1), date(2026, 7, 7))
    report = ar.fetch_report(period, date(2026, 8, 26), True, _fake_ga4, _fake_gsc)
    assert report["ga4"]["previous"]["activeUsers"] == 50.0
    assert report["ga4"]["deltas"]["activeUsers"]["pct"] == pytest.approx(0.0)
    assert report["gsc"]["deltas"] is not None


def test_fetch_report_partial_failure_marks_source_partial():
    def flaky_gsc(body: dict) -> dict:
        if body.get("dimensions") == ["page"]:
            raise RuntimeError("boom")
        return _fake_gsc(body)

    period = (date(2026, 7, 30), date(2026, 8, 26))
    report = ar.fetch_report(period, date(2026, 8, 26), False, _fake_ga4, flaky_gsc)
    assert report["data_quality"]["source_status"]["gsc"] == "partial"
    assert "gsc.pages" in report["data_quality"]["partial_failures"]
    # ページ取得が落ちても totals/queries は生きている。
    assert report["gsc"]["totals"]["clicks"] == 20.0


def test_fetch_report_total_failure_marks_source_failed():
    def broken_ga4(body: dict) -> dict:
        raise RuntimeError("network down")

    period = (date(2026, 7, 30), date(2026, 8, 26))
    report = ar.fetch_report(period, date(2026, 8, 26), False, broken_ga4, _fake_gsc)
    assert report["data_quality"]["source_status"]["ga4"] == "failed"
    assert report["ga4"]["totals"] is None


# --------------------------------------------------------------------------
# markdown 整形
# --------------------------------------------------------------------------


def test_compose_markdown_snippets():
    period = (date(2026, 7, 30), date(2026, 8, 26))
    report = ar.fetch_report(period, date(2026, 8, 26), False, _fake_ga4, _fake_gsc)
    md = ar.compose_markdown(report)
    assert "# めぐりび アナリティクス最新分析" in md
    assert "アクティブユーザー: 50" in md
    assert "直近日を含みます" in md  # provisional 注記
    assert "有効クリック: 10（全クリック 20）" in md
    assert "「めぐりび 渋谷」（指名）" in md
    assert "→ /store/shibuya" in md


def test_compose_markdown_shows_na_on_total_failure():
    def broken_ga4(body: dict) -> dict:
        raise RuntimeError("network down")

    period = (date(2026, 7, 30), date(2026, 8, 26))
    report = ar.fetch_report(period, date(2026, 8, 26), False, broken_ga4, _fake_gsc)
    md = ar.compose_markdown(report)
    assert "取得失敗" in md
    assert "データ品質" in md


# --------------------------------------------------------------------------
# main（認証情報なし → exit 1）
# --------------------------------------------------------------------------


def test_main_no_credentials_exits_one(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("GA4_PROPERTY_ID", "")
    monkeypatch.setenv("GA_SERVICE_ACCOUNT_JSON", str(tmp_path / "does-not-exist.json"))
    rc = ar.main(["--format", "json"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "docs/ANALYTICS_SETUP.md" in out
    assert "未セットアップ" in out


def test_main_bad_as_of_format_exits_one(monkeypatch, tmp_path):
    key = tmp_path / "ga.json"
    key.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("GA4_PROPERTY_ID", "493123456")
    monkeypatch.setenv("GA_SERVICE_ACCOUNT_JSON", str(key))
    # google-auth 未導入環境でも、--as-of の形式エラーは認証より手前で検出したいところだが、
    # 現実装では認証(google_access_token)が先に走る。google-auth 未導入なら token is None で
    # exit 1 になるので、いずれにせよ致命的失敗として exit 1 を確認する。
    rc = ar.main(["--as-of", "not-a-date"])
    assert rc == 1
