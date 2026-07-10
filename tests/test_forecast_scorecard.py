"""プロダクト・スコアカード純関数のテスト (scripts/score_forecasts.py)。

peak_time_hit30 の 30 分ちょうどの境界 / 有効条件、ghost_index のスロット選択、
band_coverage の割合 —— すべてネットワーク無し。
"""

from __future__ import annotations

import pytest

import scripts.score_forecasts as sf


class TestPeakTimeHit30:
    def test_boundary_exactly_30_is_hit(self) -> None:
        times = [i * 15 for i in range(20)]
        actual = [1.0] * 20
        actual[5] = 10.0
        pred = [0.0] * 20
        pred[7] = 9.0  # |7-5|*15 = 30 分ちょうど → hit
        assert sf.peak_time_hit30(times, actual, pred) is True

    def test_45_min_is_miss(self) -> None:
        times = [i * 15 for i in range(20)]
        actual = [1.0] * 20
        actual[5] = 10.0
        pred = [0.0] * 20
        pred[8] = 9.0  # |8-5|*15 = 45 分 → miss
        assert sf.peak_time_hit30(times, actual, pred) is False

    def test_ineligible_too_few_slots(self) -> None:
        times = [i * 15 for i in range(19)]  # <20 マッチ
        actual = [1.0] * 19
        actual[5] = 10.0
        pred = [0.0] * 19
        pred[5] = 9.0
        assert sf.peak_time_hit30(times, actual, pred) is None

    def test_ineligible_low_actual_peak(self) -> None:
        times = [i * 15 for i in range(20)]
        actual = [1.0] * 20
        actual[5] = 4.0  # ピーク <5 人 → 対象外
        pred = [0.0] * 20
        pred[5] = 9.0
        assert sf.peak_time_hit30(times, actual, pred) is None


class TestGhostIndex:
    def test_selects_empty_late_slots(self) -> None:
        actual = [100.0, 0.0, 0.0, 50.0]
        pred = [10.0, 8.0, 6.0, 5.0]
        late = [True, True, True, False]
        # peak=100, thr=max(1, 5)=5。late かつ actual<=5: idx1(pred8), idx2(pred6)。
        # idx0 は late だが actual=100>5 で除外、idx3 は late でない。 → mean(8,6)=7
        assert sf.ghost_index(actual, pred, late) == pytest.approx(7.0)

    def test_threshold_uses_five_percent_of_peak(self) -> None:
        actual = [200.0, 8.0]  # 5% of 200 = 10 → 8<=10 で該当
        pred = [1.0, 4.0]
        late = [True, True]
        # idx0 actual=200>10 除外, idx1 actual=8<=10 → mean(4)=4
        assert sf.ghost_index(actual, pred, late) == pytest.approx(4.0)

    def test_none_when_no_empty_late_slot(self) -> None:
        actual = [100.0, 90.0]
        pred = [10.0, 9.0]
        late = [True, True]  # どちらも thr(5) 超 → None
        assert sf.ghost_index(actual, pred, late) is None


class TestBandCoverage:
    def test_fraction(self) -> None:
        actual = [5.0, 15.0, 25.0]
        p10 = [2.0, 2.0, 2.0]
        p90 = [10.0, 20.0, 20.0]
        # 5∈[2,10] o, 15∈[2,20] o, 25∈[2,20] x → 2/3
        assert sf.band_coverage(actual, p10, p90) == pytest.approx(2 / 3)

    def test_boundary_inclusive(self) -> None:
        assert sf.band_coverage([2.0, 10.0], [2.0, 2.0], [10.0, 10.0]) == pytest.approx(1.0)

    def test_none_when_empty(self) -> None:
        assert sf.band_coverage([], [], []) is None
        assert sf.band_coverage([None], [None], [None]) is None
