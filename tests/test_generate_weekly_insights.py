"""Weekly Report v2 (2026-05) で追加したヘルパー関数の単体テスト。

対象:
- _build_day_hour_heatmap (Phase B): 0-4 時の前日扱い、サンプル無しセル、空入力
- _build_daily_summary: 夜セッション基準で 7 夜を集計
- _derive_next_week_recommendations (Phase D): サンプル数 < 2 のセル除外、上位 N
- _compute_metric_interpretations (Phase A): 1 日平均 / volume_label / baseline_label
- _extract_commentary_via_regex: JSON 破損時のフィールド単独抽出フォールバック
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from scripts.generate_weekly_insights import (
    DAY_LABELS_JA,
    HEATMAP_HOURS,
    JST_OFFSET,
    _build_daily_summary,
    _build_day_hour_heatmap,
    _compute_metric_interpretations,
    _derive_next_week_recommendations,
    _extract_commentary_via_regex,
)


def _point(jst_dt: datetime, occ: float, fr: float = 0.55) -> dict:
    """timestamp は UTC で保存される設計なので JST 入力を UTC に変換する。"""
    return {
        "timestamp": jst_dt.astimezone(timezone.utc),
        "occupancy_rate": occ,
        "female_ratio": fr,
        "stability": 1.0,
    }


def _full_week_points(occ_overrides: dict[tuple[int, int], float] | None = None) -> list[dict]:
    """月-日 7 日 × 19-04時 10 時間 × 4 サンプル/時間 = 280 ポイント。

    occ_overrides は {(day_offset, hour): occupancy} の辞書で特定セルの値を上書きする。
    day_offset=0 は 2026-04-27 (月) を起点とし、hour < 19 のものは翌日に降ろす規則。
    """
    points: list[dict] = []
    base = datetime(2026, 4, 27, tzinfo=JST_OFFSET)  # Mon
    for day_offset in range(7):
        base_day = base + timedelta(days=day_offset)
        for hour in HEATMAP_HOURS:
            for minute in (0, 15, 30, 45):
                if hour < 19:
                    ts = base_day.replace(hour=hour, minute=minute) + timedelta(days=1)
                else:
                    ts = base_day.replace(hour=hour, minute=minute)
                occ = (occ_overrides or {}).get((day_offset, hour), 0.30)
                points.append(_point(ts, occ))
    return points


# ---------------------------------------------------------------------------
# _build_day_hour_heatmap
# ---------------------------------------------------------------------------


class TestBuildDayHourHeatmap:
    def test_empty_input_returns_empty_cells(self) -> None:
        h = _build_day_hour_heatmap([])
        # cells は 7 曜日 × 10 時間で常に 70 セル返る。サンプル無しは sample_count=0。
        assert len(h["cells"]) == 70
        assert all(c["sample_count"] == 0 for c in h["cells"])
        assert h["max_avg_occupancy"] == 0
        assert h["hour_range"] == HEATMAP_HOURS
        assert h["day_labels_ja"] == DAY_LABELS_JA

    def test_uniform_occupancy_makes_all_cells_equal(self) -> None:
        h = _build_day_hour_heatmap(_full_week_points())
        non_empty = [c for c in h["cells"] if c["sample_count"] > 0]
        assert len(non_empty) == 70
        for c in non_empty:
            assert c["avg_occupancy"] == pytest.approx(0.30, abs=0.001)
            assert c["sample_count"] == 4
        assert h["max_avg_occupancy"] == pytest.approx(0.30, abs=0.001)

    def test_late_night_data_attributes_to_previous_day(self) -> None:
        # 5/2 (土) base_day で hour=22 の物理 5/2 22:00 と、
        # hour=2 の物理 5/3 02:00 (土曜の夜の続き) を高 occupancy にする。
        # → どちらも heatmap 上では Saturday (day=5) の行に集計されるべき。
        overrides = {(5, 22): 0.95, (5, 2): 0.92}
        h = _build_day_hour_heatmap(_full_week_points(overrides))
        sat_22 = next(c for c in h["cells"] if c["day"] == 5 and c["hour"] == 22)
        sat_2 = next(c for c in h["cells"] if c["day"] == 5 and c["hour"] == 2)
        sun_2 = next(c for c in h["cells"] if c["day"] == 6 and c["hour"] == 2)
        assert sat_22["avg_occupancy"] == pytest.approx(0.95, abs=0.001)
        assert sat_2["avg_occupancy"] == pytest.approx(0.92, abs=0.001)
        # 5/2 base_day の hour=2 は物理 5/3 02:00。これが日曜行に入っていないことを確認。
        # 日曜 02:00 は別の base_day=6 (日) のデータで、デフォルト 0.30。
        assert sun_2["avg_occupancy"] == pytest.approx(0.30, abs=0.001)

    def test_max_avg_occupancy_reflects_highest_cell(self) -> None:
        overrides = {(4, 22): 0.85, (5, 22): 0.95}
        h = _build_day_hour_heatmap(_full_week_points(overrides))
        assert h["max_avg_occupancy"] == pytest.approx(0.95, abs=0.001)


# ---------------------------------------------------------------------------
# _derive_next_week_recommendations
# ---------------------------------------------------------------------------


class TestDeriveNextWeekRecommendations:
    def test_returns_empty_when_no_data(self) -> None:
        h = _build_day_hour_heatmap([])
        assert _derive_next_week_recommendations(h) == []

    def test_filters_out_low_sample_count_cells(self) -> None:
        # 1 サンプルだけのセルは sample_count<2 で除外される
        single_point = [_point(datetime(2026, 4, 27, 22, 0, tzinfo=JST_OFFSET), 0.95)]
        h = _build_day_hour_heatmap(single_point)
        recs = _derive_next_week_recommendations(h)
        assert recs == []

    def test_picks_top_cells_by_avg_occupancy(self) -> None:
        # 金 21 と 土 22 と 土 23 を高くして、土 22 > 土 23 > 金 21 の順を作る
        overrides = {(4, 21): 0.80, (5, 22): 0.95, (5, 23): 0.90}
        h = _build_day_hour_heatmap(_full_week_points(overrides))
        recs = _derive_next_week_recommendations(h)
        assert len(recs) == 3
        assert recs[0]["day_label_ja"] == "土"
        assert recs[0]["hour_label"] == "22:00-23:00"
        assert recs[0]["avg_occupancy"] == pytest.approx(0.95, abs=0.001)
        assert recs[1]["day_label_ja"] == "土"
        assert recs[1]["hour_label"] == "23:00-00:00"
        assert recs[2]["day_label_ja"] == "金"
        assert recs[2]["hour_label"] == "21:00-22:00"

    def test_top_n_clamps_recommendations(self) -> None:
        h = _build_day_hour_heatmap(_full_week_points({(4, 21): 0.80, (5, 22): 0.95}))
        recs = _derive_next_week_recommendations(h, top_n=1)
        assert len(recs) == 1
        assert recs[0]["day_label_ja"] == "土"


# ---------------------------------------------------------------------------
# _build_daily_summary
# ---------------------------------------------------------------------------


class TestBuildDailySummary:
    def test_empty_input(self) -> None:
        assert _build_daily_summary([]) == []

    def test_one_full_night_session(self) -> None:
        # 5/2 (土) 19:00 -> 5/3 (日) 04:59 = 1 つの夜セッション
        points = []
        sat = datetime(2026, 5, 2, tzinfo=JST_OFFSET)
        for hour in HEATMAP_HOURS:
            for minute in (0, 30):
                if hour < 19:
                    ts = sat.replace(hour=hour, minute=minute) + timedelta(days=1)
                else:
                    ts = sat.replace(hour=hour, minute=minute)
                points.append(_point(ts, 0.5))
        summary = _build_daily_summary(points)
        assert len(summary) == 1
        assert summary[0]["date"] == "2026-05-02"
        assert summary[0]["day_label_ja"] == "土"
        assert summary[0]["sample_count"] == 20  # 10 hours x 2 minutes

    def test_peak_and_avg_are_separate(self) -> None:
        sat = datetime(2026, 5, 2, 22, 0, tzinfo=JST_OFFSET)
        points = [
            _point(sat, 0.30),
            _point(sat + timedelta(minutes=15), 0.30),
            _point(sat + timedelta(minutes=30), 0.95),  # peak
        ]
        summary = _build_daily_summary(points)
        assert len(summary) == 1
        assert summary[0]["peak_occupancy"] == pytest.approx(0.95, abs=0.001)
        # avg = (0.30 + 0.30 + 0.95) / 3
        assert summary[0]["avg_occupancy"] == pytest.approx(0.5167, abs=0.01)

    def test_excludes_daytime_data_points(self) -> None:
        # 5/2 日中 (5-18 時) のデータは sumary に含まれない
        sat = datetime(2026, 5, 2, tzinfo=JST_OFFSET)
        points = [
            _point(sat.replace(hour=12, minute=0), 0.5),
            _point(sat.replace(hour=22, minute=0), 0.5),
        ]
        summary = _build_daily_summary(points)
        assert len(summary) == 1
        assert summary[0]["sample_count"] == 1

    def test_dates_are_sorted(self) -> None:
        # 古い夜と新しい夜を逆順で投入してもソート結果で出る
        nights = []
        for d in (5, 3, 1):
            base = datetime(2026, 5, d, 22, 0, tzinfo=JST_OFFSET)
            nights.append(_point(base, 0.5))
        summary = _build_daily_summary(nights)
        assert [s["date"] for s in summary] == ["2026-05-01", "2026-05-03", "2026-05-05"]


# ---------------------------------------------------------------------------
# _compute_metric_interpretations
# ---------------------------------------------------------------------------


class TestComputeMetricInterpretations:
    def test_volume_label_平常_when_high_density(self) -> None:
        # points_count=1000, 7日 → daily_avg ~= 142.9 → 平常
        start = datetime(2026, 4, 27, tzinfo=timezone.utc)
        end = datetime(2026, 5, 3, tzinfo=timezone.utc)
        interp = _compute_metric_interpretations(1000, start, end, 80.0)
        assert interp["daily_avg_count"] == pytest.approx(142.9, abs=0.1)
        assert interp["volume_label"] == "平常"
        assert interp["baseline_label"] == "大型店レベル"
        assert interp["period_days"] == 7

    def test_volume_label_やや少なめ_when_mid_density(self) -> None:
        start = datetime(2026, 4, 27, tzinfo=timezone.utc)
        end = datetime(2026, 5, 3, tzinfo=timezone.utc)
        interp = _compute_metric_interpretations(500, start, end, 50.0)
        assert interp["volume_label"] == "やや少なめ"
        assert interp["baseline_label"] == "中規模店レベル"

    def test_volume_label_少ない_when_low_density(self) -> None:
        start = datetime(2026, 4, 27, tzinfo=timezone.utc)
        end = datetime(2026, 5, 3, tzinfo=timezone.utc)
        interp = _compute_metric_interpretations(200, start, end, 20.0)
        assert interp["volume_label"] == "少ない"
        assert interp["baseline_label"] == "小規模店または閑散時間が多め"

    def test_handles_missing_period_dates(self) -> None:
        interp = _compute_metric_interpretations(100, None, None, 50.0)
        assert interp["period_days"] == 7  # default
        assert interp["daily_avg_count"] > 0


# ---------------------------------------------------------------------------
# _extract_commentary_via_regex
# ---------------------------------------------------------------------------


class TestExtractCommentaryViaRegex:
    def test_returns_none_for_empty_input(self) -> None:
        assert _extract_commentary_via_regex("") is None
        assert _extract_commentary_via_regex("not json at all") is None

    def test_extracts_both_fields_from_well_formed_json(self) -> None:
        raw = (
            '{"last_week_summary": "先週は週末を中心に賑わいました。", '
            '"next_week_forecast": "来週も同じパターンが続きそうです。"}'
        )
        out = _extract_commentary_via_regex(raw)
        assert out is not None
        assert out["last_week_summary"] == "先週は週末を中心に賑わいました。"
        assert out["next_week_forecast"] == "来週も同じパターンが続きそうです。"

    def test_handles_escaped_newline_inside_string(self) -> None:
        raw = (
            '{"last_week_summary": "リード文。\\n- 金曜が高い\\n- 土曜も高い", '
            '"next_week_forecast": "来週は…"}'
        )
        out = _extract_commentary_via_regex(raw)
        assert out is not None
        assert "\n" in out["last_week_summary"]
        assert "金曜が高い" in out["last_week_summary"]

    def test_returns_partial_when_only_one_field_present(self) -> None:
        # next_week_forecast が見つからなくても last_week_summary だけ返す
        raw = '{"last_week_summary": "先週はこうでした。"}'
        out = _extract_commentary_via_regex(raw)
        assert out is not None
        assert out["last_week_summary"] == "先週はこうでした。"
        assert "next_week_forecast" not in out

    def test_empty_string_value_does_not_extract(self) -> None:
        # 空文字列は extract しない (「あったが空」と「無かった」を区別する必要なし)
        raw = '{"last_week_summary": "", "next_week_forecast": ""}'
        out = _extract_commentary_via_regex(raw)
        assert out is None
