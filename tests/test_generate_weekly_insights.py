"""Weekly Report v2 (2026-05) で追加したヘルパー関数の単体テスト。

対象:
- _build_day_hour_heatmap (Phase B): 0-4 時の前日扱い、サンプル無しセル、空入力
- _build_daily_summary: 夜セッション基準で 7 夜を集計
- _derive_next_week_recommendations (Phase D): サンプル数 < 2 のセル除外、上位 N
- _compute_metric_interpretations (Phase A): 1 日平均 / volume_label / baseline_label
- _extract_commentary_via_regex: JSON 破損時のフィールド単独抽出フォールバック
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

import pytest

import scripts.generate_weekly_insights as gwi
from scripts.generate_weekly_insights import (
    DAY_LABELS_JA,
    DEFAULT_WEEKLY_MIN_NIGHT_SAMPLES,
    HEATMAP_HOURS,
    JST_OFFSET,
    NIGHT_SESSION_SHIFT_HOURS,
    _build_busy_windows,
    _build_daily_summary,
    _build_day_hour_heatmap,
    _compute_metric_interpretations,
    _derive_next_week_recommendations,
    _extract_commentary_via_regex,
    _load_store_active_map,
    _night_date,
    _truncate_points_to_recent_nights,
    _weekly_skip_reason,
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
# _night_date: -6h シフト規約 (oriental/ml/night_type.py と単一ソース) への統一 (C1)
# ---------------------------------------------------------------------------


class TestNightDateSharedConvention:
    """_night_date は oriental/ml/night_type.py の NIGHT_SESSION_SHIFT_HOURS (=6) を
    単一ソースとする -6h シフト規約に従う。2026-07-11 に旧 `hour < 5` から統一した
    (実データに JST 5時台の行が存在しないため出力への影響はゼロ。CLAUDE.md 罠#2 参照)。
    """

    def test_shift_hours_is_six(self) -> None:
        assert NIGHT_SESSION_SHIFT_HOURS == 6

    def test_0530_belongs_to_previous_night(self) -> None:
        # 05:30 は旧実装 (hour<5) では「当日」扱いだったが、-6h規約では前夜に属する。
        ts = datetime(2026, 5, 3, 5, 30, tzinfo=JST_OFFSET)
        assert _night_date(ts) == (ts - timedelta(days=1)).date() == datetime(2026, 5, 2).date()

    def test_0630_belongs_to_same_day(self) -> None:
        ts = datetime(2026, 5, 3, 6, 30, tzinfo=JST_OFFSET)
        assert _night_date(ts) == ts.date() == datetime(2026, 5, 3).date()

    def test_boundary_at_exactly_0559_and_0600(self) -> None:
        just_before = datetime(2026, 5, 3, 5, 59, tzinfo=JST_OFFSET)
        just_after = datetime(2026, 5, 3, 6, 0, tzinfo=JST_OFFSET)
        assert _night_date(just_before) == datetime(2026, 5, 2).date()
        assert _night_date(just_after) == datetime(2026, 5, 3).date()

    def test_1900_start_of_session_is_same_day(self) -> None:
        ts = datetime(2026, 5, 2, 19, 0, tzinfo=JST_OFFSET)
        assert _night_date(ts) == datetime(2026, 5, 2).date()


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


# ---------------------------------------------------------------------------
# fix #2: _build_busy_windows — 素の occupancy でランク付けする賑わい窓
# ---------------------------------------------------------------------------


def _packed_night_points(
    night_date: datetime,
    packed_hours: tuple[int, ...],
    occ: float,
    fr: float,
    per_hour: int = 4,
) -> list[dict]:
    """指定した夜の packed_hours を occ で埋めた points を作る。hour<19 は翌日に降ろす。"""
    pts: list[dict] = []
    for hour in packed_hours:
        for i in range(per_hour):
            minute = int(60 * i / per_hour)
            ts = night_date.replace(hour=hour, minute=minute)
            if hour < 19:
                ts = ts + timedelta(days=1)
            pts.append(_point(ts, occ, fr))
    return pts


class TestBuildBusyWindows:
    def test_ranks_by_plain_occupancy_and_drops_empty(self) -> None:
        # 満席の土曜深夜窓 (occ 0.98, 女性比 0.45 = 低) を採用し、空いた時間 (occ 0.05) は
        # 窓にならないこと。旧合成スコアなら満席窓は occ_score=0 で脱落していた (fix #2)。
        sat = datetime(2026, 5, 2, tzinfo=JST_OFFSET)
        points = _packed_night_points(sat, (22, 23, 0, 1, 2), 0.98, 0.45)
        # 別の空き時間帯 (occ 0.05) を混ぜる → 閾値未満で窓にならない
        for minute in range(0, 60, 5):
            points.append(_point(sat.replace(hour=3, minute=minute) + timedelta(days=1), 0.05))

        windows = _build_busy_windows(points, occupancy_threshold=0.40, min_duration_minutes=60)
        assert len(windows) == 1
        assert windows[0]["avg_score"] == pytest.approx(0.98, abs=0.01)
        assert windows[0]["duration_minutes"] >= 60

    def test_empty_input_returns_no_windows(self) -> None:
        assert _build_busy_windows([], 0.40, 60) == []

    def test_gap_between_nights_splits_windows(self) -> None:
        # 2 夜連続で満席。日中サンプルが無くても max_gap で夜が分割され、
        # 1 つの巨大窓にマージされないこと。
        fri = datetime(2026, 5, 1, tzinfo=JST_OFFSET)
        sat = datetime(2026, 5, 2, tzinfo=JST_OFFSET)
        points = _packed_night_points(fri, (22, 23, 0, 1), 0.95, 0.5)
        points += _packed_night_points(sat, (22, 23, 0, 1), 0.95, 0.5)
        windows = _build_busy_windows(points, 0.40, 60)
        assert len(windows) == 2

    def test_top_window_day_matches_top_recommendation(self) -> None:
        # 賑わい窓の最上位と 狙い目TOP3 の最上位が同じ曜日を指す (両者が矛盾しない)。
        overrides = {}
        for h in (22, 23, 0, 1):
            overrides[(5, h)] = 1.0  # 土: 最も混雑
            overrides[(4, h)] = 0.9  # 金: 次点
        points = _truncate_points_to_recent_nights(_full_week_points(overrides))
        windows = _build_busy_windows(points, 0.40, 60)
        top_windows = sorted(windows, key=lambda w: w["avg_score"], reverse=True)
        assert top_windows, "少なくとも 1 つの賑わい窓が検出されるはず"
        top_start_jst = top_windows[0]["start"].astimezone(JST_OFFSET)
        top_window_day = _night_date(top_start_jst).weekday()

        recs = _derive_next_week_recommendations(_build_day_hour_heatmap(points))
        assert recs
        assert recs[0]["day"] == top_window_day == 5  # 土曜で一致


# ---------------------------------------------------------------------------
# fix #6: _truncate_points_to_recent_nights — 全 consumer を直近7夜に揃える
# ---------------------------------------------------------------------------


def _night_points_for_dates(dates: list[datetime], occ: float = 0.30, per_hour: int = 4) -> list[dict]:
    """複数の「夜」ぶんの points を作る。各 dates 要素はその夜の 00:00 JST。"""
    pts: list[dict] = []
    for base_day in dates:
        pts += _packed_night_points(base_day, tuple(HEATMAP_HOURS), occ, 0.55, per_hour)
    return pts


class TestTruncatePointsToRecentNights:
    def test_truncation_makes_heatmap_count_equal_summary_count(self) -> None:
        # 9 夜 (月曜/火曜が 2 回ずつ登場) を投入。切り詰め前はヒートマップ件数 > サマリ件数
        # (8-9 夜目が同一曜日セルに二重計上される) だが、切り詰め後は完全一致する。
        dates = [datetime(2026, 4, 27, tzinfo=JST_OFFSET) + timedelta(days=i) for i in range(9)]
        points = _night_points_for_dates(dates)

        hm_before = _build_day_hour_heatmap(points)
        ds_before = _build_daily_summary(points)
        cnt_hm_before = sum(c["sample_count"] for c in hm_before["cells"])
        cnt_ds_before = sum(d["sample_count"] for d in ds_before)
        assert cnt_hm_before > cnt_ds_before  # 切り詰め前の不整合 (バグ) を実証

        truncated = _truncate_points_to_recent_nights(points)
        hm = _build_day_hour_heatmap(truncated)
        ds = _build_daily_summary(truncated)
        cnt_hm = sum(c["sample_count"] for c in hm["cells"])
        cnt_ds = sum(d["sample_count"] for d in ds)
        assert cnt_hm == cnt_ds == len(truncated)
        assert len(ds) == 7  # 直近7夜ちょうど

    def test_daytime_points_are_dropped(self) -> None:
        # 日中 (12 時) の点は夜レポートの母集団ではないため切り詰めで落ちる。
        sat = datetime(2026, 5, 2, tzinfo=JST_OFFSET)
        points = [
            _point(sat.replace(hour=12, minute=0), 0.5),  # 日中 → 除外
            _point(sat.replace(hour=22, minute=0), 0.5),  # 夜 → 残る
        ]
        truncated = _truncate_points_to_recent_nights(points)
        assert len(truncated) == 1
        assert truncated[0]["timestamp"].astimezone(JST_OFFSET).hour == 22

    def test_empty_input(self) -> None:
        assert _truncate_points_to_recent_nights([]) == []


# ---------------------------------------------------------------------------
# fix #5: 収集停止店 (stale) のスキップ判定 / active フラグ
# ---------------------------------------------------------------------------


class TestWeeklySkipReason:
    def _now(self) -> datetime:
        return datetime(2026, 7, 10, tzinfo=timezone.utc)

    def test_active_false_skips(self) -> None:
        r = _weekly_skip_reason(
            store="sapporo_ag",
            active_map={"sapporo_ag": False},
            period_end=self._now() - timedelta(days=1),
            now=self._now(),
            stale_days=10,
        )
        assert r is not None and "active=false" in r

    def test_stale_data_skips(self) -> None:
        # sapporo_ag 実例: 最新データ 2026-05-11 を 2026-07-10 に生成 → ~60 日で古い
        r = _weekly_skip_reason(
            store="sapporo_ag",
            active_map={},
            period_end=datetime(2026, 5, 11, tzinfo=timezone.utc),
            now=self._now(),
            stale_days=10,
        )
        assert r is not None and "古" in r

    def test_no_data_skips(self) -> None:
        r = _weekly_skip_reason(
            store="x", active_map={}, period_end=None, now=self._now(), stale_days=10
        )
        assert r is not None

    def test_fresh_data_proceeds(self) -> None:
        r = _weekly_skip_reason(
            store="ebisu",
            active_map={},
            period_end=self._now() - timedelta(days=2),
            now=self._now(),
            stale_days=10,
        )
        assert r is None

    def test_active_true_still_gated_by_freshness(self) -> None:
        # active=true でも古ければスキップ / 新しければ生成
        assert (
            _weekly_skip_reason(
                store="x",
                active_map={"x": True},
                period_end=datetime(2026, 5, 11, tzinfo=timezone.utc),
                now=self._now(),
                stale_days=10,
            )
            is not None
        )
        assert (
            _weekly_skip_reason(
                store="x",
                active_map={"x": True},
                period_end=self._now() - timedelta(days=3),
                now=self._now(),
                stale_days=10,
            )
            is None
        )


class TestLoadStoreActiveMap:
    def test_returns_dict_and_healthy_stores_not_inactive(self) -> None:
        m = _load_store_active_map()
        assert isinstance(m, dict)
        # 現行 stores.json は active フィールドを持たない → 全店 active (map に載らない)。
        # 42 店の健全店を誤ってスキップしないことの回帰ガード。
        for slug in ("shibuya", "ebisu", "fukuoka", "ay_shibuya"):
            assert m.get(slug) is not False


# ---------------------------------------------------------------------------
# fix #12: 日別サマリの観測数足切り (low_sample フラグ)
# ---------------------------------------------------------------------------


class TestDailySummaryLowSampleGuard:
    def test_thin_night_flagged_low_sample(self) -> None:
        # kokura 07-01=6件 / utsunomiya 07-06=17件 のような薄い夜
        base = datetime(2026, 5, 2, 22, 0, tzinfo=JST_OFFSET)
        points = [_point(base + timedelta(minutes=5 * i), 0.5) for i in range(5)]
        summary = _build_daily_summary(points)
        assert len(summary) == 1
        assert summary[0]["sample_count"] == 5
        assert summary[0]["low_sample"] is True

    def test_full_night_not_flagged(self) -> None:
        sat = datetime(2026, 5, 2, tzinfo=JST_OFFSET)
        points = _packed_night_points(sat, tuple(HEATMAP_HOURS), 0.5, 0.55)  # 10h x 4 = 40
        summary = _build_daily_summary(points)
        assert len(summary) == 1
        assert summary[0]["sample_count"] == 40
        assert summary[0]["low_sample"] is False

    def test_default_threshold_is_documented_constant(self) -> None:
        # 既定閾値 (24) は ~120 の健全夜のおよそ 20%。境界の実証。
        assert DEFAULT_WEEKLY_MIN_NIGHT_SAMPLES == 24
        base = datetime(2026, 5, 2, 22, 0, tzinfo=JST_OFFSET)
        pts_23 = [_point(base + timedelta(minutes=2 * i), 0.5) for i in range(23)]
        pts_24 = [_point(base + timedelta(minutes=2 * i), 0.5) for i in range(24)]
        assert _build_daily_summary(pts_23)[0]["low_sample"] is True
        assert _build_daily_summary(pts_24)[0]["low_sample"] is False

    def test_param_override_changes_threshold(self) -> None:
        base = datetime(2026, 5, 2, 22, 0, tzinfo=JST_OFFSET)
        points = [_point(base + timedelta(minutes=2 * i), 0.5) for i in range(30)]
        assert _build_daily_summary(points, min_night_samples=24)[0]["low_sample"] is False
        assert _build_daily_summary(points, min_night_samples=40)[0]["low_sample"] is True


# ---------------------------------------------------------------------------
# 2026-07-18 index.json retirement: main() must no longer create/rewrite
# frontend/content/insights/weekly/index.json under any circumstance. Verified
# to have zero frontend readers by grepping frontend/src: the weekly report page
# (frontend/src/app/reports/weekly/[store_slug]/page.tsx) fetches from Supabase
# blog_drafts directly, and sitemap.ts derives lastModified from a directory
# listing of each store's dated JSON files (fs.readdirSync), never index.json.
# ---------------------------------------------------------------------------


def _run_main_dry(tmp_path, monkeypatch, extra_argv: list[str]) -> int:
    """Run generate_weekly_insights.main() as a read-only dry run.

    - REPO_ROOT is monkeypatched to an isolated tmp_path so nothing is ever
      written under the real frontend/content/insights/weekly (production
      content is never touched by this test).
    - _load_rows is stubbed to return no rows for any store, so every store
      hits the "no timestamped data" skip path immediately (no real HTTP
      fetch, no Ollama call, no Supabase upsert).
    """
    monkeypatch.setattr(gwi, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(gwi, "_load_rows", lambda *a, **kw: [])
    monkeypatch.setattr(gwi, "_load_store_active_map", lambda: {})
    monkeypatch.delenv("INSIGHTS_SYNC_SUPABASE", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        ["generate_weekly_insights.py", "--stores", "shibuya,ebisu", *extra_argv],
    )
    return gwi.main()


class TestIndexJsonRetired:
    def test_skip_index_flag_still_accepted_but_writes_nothing(self, tmp_path, monkeypatch) -> None:
        # generate-weekly-insights.yml (GHA 緊急手動実行) は今も --skip-index を渡す。
        # argparse がこのフラグを拒否しない (後方互換の no-op) ことを確認する。
        rc = _run_main_dry(tmp_path, monkeypatch, ["--skip-index"])
        assert rc == 0
        index_path = tmp_path / "frontend" / "content" / "insights" / "weekly" / "index.json"
        assert not index_path.exists()

    def test_no_skip_index_flag_also_writes_nothing(self, tmp_path, monkeypatch) -> None:
        # --skip-index を付けなくても index.json は生成されない
        # (真の退役: フラグの有無に関係なく書き込みコード自体が無い)。
        rc = _run_main_dry(tmp_path, monkeypatch, [])
        assert rc == 0
        index_path = tmp_path / "frontend" / "content" / "insights" / "weekly" / "index.json"
        assert not index_path.exists()

    def test_preexisting_stale_index_json_is_left_untouched(self, tmp_path, monkeypatch) -> None:
        # 2026-06-30 で凍結していたような既存の index.json が万一残っていても、
        # main() はそれを読みも書きもしない (バイト単位で不変)。
        weekly_dir = tmp_path / "frontend" / "content" / "insights" / "weekly"
        weekly_dir.mkdir(parents=True)
        index_path = weekly_dir / "index.json"
        stale_content = '{"generated_at": "2026-06-30T00:00:00+00:00", "stores": {}}'
        index_path.write_text(stale_content, encoding="utf-8")

        rc = _run_main_dry(tmp_path, monkeypatch, [])
        assert rc == 0
        assert index_path.read_text(encoding="utf-8") == stale_content
