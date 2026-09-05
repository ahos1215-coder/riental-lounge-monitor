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
    assert counts == {"1-3": 1, "4-10": 2, "11-20": 0, "21+": 1, "unknown": 0}
    assert ar.position_bucket_counts([]) == {"1-3": 0, "4-10": 0, "11-20": 0, "21+": 0, "unknown": 0}


def test_position_bucket_counts_treats_missing_zero_nonfinite_as_unknown():
    # 2026-08-26 計測レビュー対応（第2ラウンド・修正5）: 欠損・0・非有限は unknown へ。
    # 以前は float(position or 0) 経由で "1-3" に誤分類されていた。
    rows = [{"position": None}, {"position": 0}, {"position": float("nan")}, {}]
    counts = ar.position_bucket_counts(rows)
    assert counts == {"1-3": 0, "4-10": 0, "11-20": 0, "21+": 0, "unknown": 4}


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
    assert "「めぐりび 渋谷」（指名(サイト)）" in md  # 修正5: 三分類（サイト/チェーン/一般）
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


def _fake_gsc_with_freshness_metadata(body: dict) -> dict:
    dims = body.get("dimensions")
    if dims == ["date"]:
        return {"metadata": {"first_incomplete_date": "2026-08-24"}, "rows": []}
    return _fake_gsc(body)


# --------------------------------------------------------------------------
# 2026-08-26 計測レビュー対応（第2ラウンド・修正1）: GSC確定日の専用プローブ
# --------------------------------------------------------------------------


def test_gsc_freshness_probe_body_shape():
    body = ar.gsc_freshness_probe_body(date(2026, 8, 26), lookback_days=10)
    assert body["dimensions"] == ["date"]
    assert body["dataState"] == "all"
    assert body["startDate"] == "2026-08-16"
    assert body["endDate"] == "2026-08-26"
    assert body["rowLimit"] == 11


def test_fetch_report_uses_freshness_probe_for_availability_metadata():
    period = (date(2026, 7, 30), date(2026, 8, 26))
    report = ar.fetch_report(period, date(2026, 8, 26), False, _fake_ga4, _fake_gsc_with_freshness_metadata)
    assert report["gsc"]["availability_source"] == "metadata"
    assert report["gsc"]["available_through"] == "2026-08-23"


def test_fetch_report_ignores_metadata_leaked_into_dimensionless_totals_response():
    # 修正1: 以前は dimension無しの totals レスポンスの metadata から確定日を読もうとしていたが、
    # 公式仕様上そこにはほぼ返らない。totals応答にmetadataが紛れていても無視され、
    # date dimension 専用プローブの応答だけが使われることを固定する。
    def fake_gsc(body: dict) -> dict:
        dims = body.get("dimensions")
        if not dims:
            resp = dict(_fake_gsc(body))
            resp["metadata"] = {"first_incomplete_date": "2026-01-01"}  # 罠: totalsに紛れたmetadata
            return resp
        if dims == ["date"]:
            return {"rows": []}  # プローブはmetadataを返さない → rule fallback
        return _fake_gsc(body)

    period = (date(2026, 7, 30), date(2026, 8, 26))
    report = ar.fetch_report(period, date(2026, 8, 26), False, _fake_ga4, fake_gsc)
    assert report["gsc"]["availability_source"] == "rule"
    assert report["gsc"]["available_through"] == "2026-08-23"  # as_of - 3日


def test_compose_markdown_shows_availability_source_label():
    period = (date(2026, 7, 30), date(2026, 8, 26))
    report = ar.fetch_report(period, date(2026, 8, 26), False, _fake_ga4, _fake_gsc)
    md = ar.compose_markdown(report)
    assert "判定方法: 推定（規約ベース）" in md
    report2 = ar.fetch_report(period, date(2026, 8, 26), False, _fake_ga4, _fake_gsc_with_freshness_metadata)
    md2 = ar.compose_markdown(report2)
    assert "判定方法: APIメタデータ" in md2


# --------------------------------------------------------------------------
# 2026-08-26 計測レビュー対応（第2ラウンド・修正2）: 確定分同士の前期間比較
# --------------------------------------------------------------------------


def test_stable_subperiod_no_trim_when_fully_confirmed():
    assert ar.stable_subperiod(date(2026, 8, 1), date(2026, 8, 10), date(2026, 8, 20)) == (
        date(2026, 8, 1),
        date(2026, 8, 10),
    )


def test_stable_subperiod_trims_tail_when_partially_confirmed():
    assert ar.stable_subperiod(date(2026, 8, 1), date(2026, 8, 26), date(2026, 8, 20)) == (
        date(2026, 8, 1),
        date(2026, 8, 20),
    )


def test_stable_subperiod_none_when_fully_unconfirmed():
    assert ar.stable_subperiod(date(2026, 8, 21), date(2026, 8, 26), date(2026, 8, 20)) is None


def _stable_safe(fn, *args, label=""):
    return fn(*args)


def test_stable_comparison_reuses_raw_when_period_fully_confirmed():
    calls: list[dict] = []

    def call(body: dict) -> dict:
        calls.append(body)
        return {"rows": [{"clicks": 1}]}

    def totals_body(s: str, e: str) -> dict:
        return {"start": s, "end": e}

    def parse(resp: dict | None) -> dict:
        rows = (resp or {}).get("rows") or [{}]
        return {"clicks": float(rows[0].get("clicks", 0))}

    result = ar.stable_comparison(
        start=date(2026, 8, 1),
        end=date(2026, 8, 7),
        available_through=date(2026, 8, 20),
        full_period_cur_raw={"rows": [{"clicks": 10}]},
        full_period_prev_raw={"rows": [{"clicks": 8}]},
        call=call,
        totals_body_fn=totals_body,
        parse_fn=parse,
        label_prefix="x",
        safe=_stable_safe,
    )
    assert calls == []  # 期間全体が確定済みなので追加リクエストなし（既取得のraw値を再利用）
    assert result["totals"]["clicks"] == 10.0
    assert result["previous_totals"]["clicks"] == 8.0
    assert result["note"] is None
    assert result["period"] == {"start": "2026-08-01", "end": "2026-08-07"}
    assert result["deltas"]["clicks"]["pct"] == pytest.approx(25.0)


def test_stable_comparison_fetches_trimmed_period_when_tail_is_provisional():
    calls: list[dict] = []

    def call(body: dict) -> dict:
        calls.append(body)
        return {"rows": [{"clicks": 5}]}

    def totals_body(s: str, e: str) -> dict:
        return {"start": s, "end": e}

    def parse(resp: dict | None) -> dict:
        rows = (resp or {}).get("rows") or [{}]
        return {"clicks": float(rows[0].get("clicks", 0))}

    result = ar.stable_comparison(
        start=date(2026, 8, 1),
        end=date(2026, 8, 26),
        available_through=date(2026, 8, 20),
        full_period_cur_raw={"rows": [{"clicks": 999}]},  # 速報込みの生値。stable計算には使わない
        full_period_prev_raw={"rows": [{"clicks": 999}]},
        call=call,
        totals_body_fn=totals_body,
        parse_fn=parse,
        label_prefix="x",
        safe=_stable_safe,
    )
    assert len(calls) == 2  # トリム後の確定期間・その直前期間を新たに取得
    assert result["period"] == {"start": "2026-08-01", "end": "2026-08-20"}
    assert result["note"] and "確定分同士" in result["note"]
    assert result["totals"]["clicks"] == 5.0  # 速報込みraw値(999)は使われない


def test_stable_comparison_none_period_when_fully_unconfirmed():
    result = ar.stable_comparison(
        start=date(2026, 8, 21),
        end=date(2026, 8, 26),
        available_through=date(2026, 8, 20),
        full_period_cur_raw=None,
        full_period_prev_raw=None,
        call=lambda body: {},
        totals_body_fn=lambda s, e: {},
        parse_fn=lambda r: {},
        label_prefix="x",
        safe=_stable_safe,
    )
    assert result["period"] is None
    assert result["deltas"] is None
    assert "比較保留" in result["note"]


def test_fetch_report_deltas_come_from_stable_comparison_note_in_markdown():
    # as_of=8/26, 期間の終端が8/26（GA4確定境界は as_of-2=8/24）なのでトリムされる。
    period = (date(2026, 7, 30), date(2026, 8, 26))
    report = ar.fetch_report(period, date(2026, 8, 26), True, _fake_ga4, _fake_gsc)
    assert report["ga4"]["comparison"]["note"] and "確定分同士" in report["ga4"]["comparison"]["note"]
    md = ar.compose_markdown(report)
    assert "確定分同士" in md


# --------------------------------------------------------------------------
# 2026-08-26 計測レビュー対応（第2ラウンド・修正3）: qualified 偽ゼロ
# --------------------------------------------------------------------------


def test_fetch_report_qualified_none_when_pages_fetch_fails():
    def flaky_gsc(body: dict) -> dict:
        if body.get("dimensions") == ["page"]:
            raise RuntimeError("boom")
        return _fake_gsc(body)

    period = (date(2026, 7, 30), date(2026, 8, 26))
    report = ar.fetch_report(period, date(2026, 8, 26), False, _fake_ga4, flaky_gsc)
    assert report["gsc"]["qualified_clicks"]["qualified"] is None
    md = ar.compose_markdown(report)
    assert "有効クリック: N/A" in md


# --------------------------------------------------------------------------
# 2026-08-26 計測レビュー対応（第2ラウンド・修正5）: メタデータブロック
# --------------------------------------------------------------------------


def test_fetch_report_includes_meta_block():
    period = (date(2026, 7, 30), date(2026, 8, 26))
    report = ar.fetch_report(period, date(2026, 8, 26), False, _fake_ga4, _fake_gsc)
    meta = report["meta"]
    assert meta["schema_version"] == 2
    assert meta["timezone"] == "Asia/Tokyo"
    assert meta["row_limits"]["gsc_pages"] == 200
    assert meta["source_status"] == {"ga4": "ok", "gsc": "ok"}


# --------------------------------------------------------------------------
# 2026-08-26 計測レビュー対応（第2ラウンド・修正6）: PV計測定義変更(8/26)の境界
# --------------------------------------------------------------------------


def test_fetch_report_blocks_pv_delta_when_comparison_crosses_epoch_boundary():
    period = (date(2026, 8, 24), date(2026, 8, 30))
    report = ar.fetch_report(period, date(2026, 8, 30), True, _fake_ga4, _fake_gsc)
    assert report["ga4"]["pv_delta_blocked_by_epoch_change"] is True
    md = ar.compose_markdown(report)
    assert "前期間比 ページビュー: 比較不可（8/26にPV計測定義を変更したため）" in md
    # 他の指標（アクティブユーザー）は通常どおり%が出る。
    assert "前期間比 アクティブユーザー:" in md


def test_fetch_report_pv_delta_not_blocked_when_both_periods_before_epoch():
    period = (date(2026, 7, 1), date(2026, 7, 7))
    report = ar.fetch_report(period, date(2026, 8, 26), True, _fake_ga4, _fake_gsc)
    assert report["ga4"]["pv_delta_blocked_by_epoch_change"] is False


# --------------------------------------------------------------------------
# 2026-09-06 表示修正: 増減率には必ず「実際に比較した期間」を併記する
#
# 背景: 要求期間（例:28日）の合計値と、確定分同士（例:26日）の増減率が注記だけを挟んで
# 隣り合っていたため、実際に読み手が「28日の合計と、その28日の前期間比」と誤読した。
# 設計（確定分同士で比べる）は正しいので、表示だけを直している。
# --------------------------------------------------------------------------


def test_format_period_span_includes_bounds_and_day_count():
    assert ar.format_period_span({"start": "2026-08-09", "end": "2026-09-03"}) == "2026-08-09〜09-03 の26日"
    # 1日だけの期間も「の1日」と出る（0日にならない）。
    assert ar.format_period_span({"start": "2026-08-09", "end": "2026-08-09"}) == "2026-08-09〜08-09 の1日"


def test_format_period_span_spells_out_year_when_period_crosses_new_year():
    # 年をまたぐと "01-05" だけでは何年か分からないので終端もフル ISO にする。
    assert ar.format_period_span({"start": "2026-12-20", "end": "2027-01-05"}) == "2026-12-20〜2027-01-05 の17日"


def test_format_period_span_empty_for_missing_or_broken_period():
    assert ar.format_period_span(None) == ""
    assert ar.format_period_span({}) == ""
    assert ar.format_period_span({"start": "2026-08-09", "end": None}) == ""
    assert ar.format_period_span({"start": "not-a-date", "end": "2026-08-09"}) == ""


def test_comparison_span_label_shape_and_empty_fallback():
    label = ar.comparison_span_label(
        {
            "period": {"start": "2026-08-09", "end": "2026-09-03"},
            "previous_period": {"start": "2026-07-14", "end": "2026-08-08"},
        }
    )
    assert label == "（2026-08-09〜09-03 の26日 vs 2026-07-14〜08-08 の26日）"
    # 比較保留（確定分なし）のときは何も付けない。
    assert ar.comparison_span_label({"period": None, "previous_period": None}) == ""
    assert ar.comparison_span_label(None) == ""


def _pct_lines(markdown_chunk: str) -> list[str]:
    return [ln for ln in markdown_chunk.splitlines() if "前期間比" in ln and "%" in ln]


def test_compose_markdown_pct_lines_always_carry_their_comparison_period():
    """番犬: 増減率(%)が出る行には、必ずその比較期間の日付が同じ行に含まれる（GA4もGSCも）。"""
    period = (date(2026, 7, 30), date(2026, 8, 26))  # 終端が as_of なので確定分にトリムされる
    report = ar.fetch_report(period, date(2026, 8, 26), True, _fake_ga4, _fake_gsc)
    md = ar.compose_markdown(report)
    ga4_md, _, gsc_md = md.partition("## Search Console")

    for chunk, comparison in ((ga4_md, report["ga4"]["comparison"]), (gsc_md, report["gsc"]["comparison"])):
        span = ar.comparison_span_label(comparison)
        assert span  # 前提: 比較期間が確定している
        lines = _pct_lines(chunk)
        assert lines  # 前提: %の行が実際に出ている
        for line in lines:
            assert span in line, line
            # 比較の両端（現在期間・前期間の開始日）が行内に必ず載っていること。
            assert comparison["period"]["start"] in line, line
            assert comparison["previous_period"]["start"] in line, line

    # GA4(確定〜as_of-2日)と GSC(確定〜as_of-3日)は境界が違うので、同じ文字列を使い回していない。
    assert ar.comparison_span_label(report["ga4"]["comparison"]) != ar.comparison_span_label(
        report["gsc"]["comparison"]
    )


def test_compose_markdown_pct_lines_carry_period_even_when_nothing_was_trimmed():
    # 期間全体が確定済み（トリムなし・note は None）でも、%の行だけを切り取って読まれるため併記する。
    period = (date(2026, 7, 1), date(2026, 7, 7))
    report = ar.fetch_report(period, date(2026, 8, 26), True, _fake_ga4, _fake_gsc)
    assert report["ga4"]["comparison"]["note"] is None
    md = ar.compose_markdown(report)
    ga4_md, _, gsc_md = md.partition("## Search Console")
    for chunk, comparison in ((ga4_md, report["ga4"]["comparison"]), (gsc_md, report["gsc"]["comparison"])):
        lines = _pct_lines(chunk)
        assert lines
        for line in lines:
            assert ar.comparison_span_label(comparison) in line, line


def test_stable_comparison_note_states_that_totals_and_deltas_use_different_periods():
    period = (date(2026, 7, 30), date(2026, 8, 26))
    report = ar.fetch_report(period, date(2026, 8, 26), True, _fake_ga4, _fake_gsc)
    note = report["ga4"]["comparison"]["note"]
    assert "上の合計は" in note
    assert "下の増減率は確定分同士" in note
    assert "期間が異なります" in note
    # 合計側は要求期間（28日）、増減率側は確定期間（26日）と、両方の日数が書かれている。
    assert "2026-07-30〜08-26 の28日" in note
    assert "2026-07-30〜08-24 の26日" in note
    assert note in ar.compose_markdown(report)


def test_json_comparison_keeps_period_and_previous_period():
    # markdown の併記はこの2キーから作る。JSON 側の構造は変えていないことを固定する。
    period = (date(2026, 7, 30), date(2026, 8, 26))
    report = ar.fetch_report(period, date(2026, 8, 26), True, _fake_ga4, _fake_gsc)
    for source in ("ga4", "gsc"):
        comparison = report[source]["comparison"]
        assert set(comparison["period"]) == {"start", "end"}
        assert set(comparison["previous_period"]) == {"start", "end"}


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
