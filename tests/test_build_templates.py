"""scripts/build_templates.py の純関数テスト（合成夜のみ・ネットワーク無し）。

検証対象: スロット index、百分位、夜曲線の畳み込みと窓除外、テンプレ算出
(シェイプ正規化 / 分位 / 男性比 / スケール基準)、特別期間の除外、フォールバック梯子。
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

import scripts.build_templates as bt


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def make_night(totals: list[float], men_frac: float = 0.6) -> dict[int, dict[str, float]]:
    """40 スロット全て観測済みの合成夜（build_template が採用できる形）。"""
    slots: dict[int, dict[str, float]] = {}
    for i, t in enumerate(totals):
        e: dict[str, float] = {"total": float(t)}
        if t > 0:
            e["men"] = t * men_frac
            e["women"] = t * (1.0 - men_frac)
        slots[i] = e
    return slots


def flat_night(total_sum: float, men_frac: float = 0.6) -> dict[int, dict[str, float]]:
    """夜合計 = total_sum、40 スロット均等の夜（シェイプ=一様 1/40）。"""
    return make_night([total_sum / bt.SLOTS] * bt.SLOTS, men_frac=men_frac)


# --------------------------------------------------------------------------- #
# slot_index / percentile
# --------------------------------------------------------------------------- #
class TestSlotIndex:
    def test_boundaries(self) -> None:
        assert bt.slot_index(19, 0) == 0
        assert bt.slot_index(19, 14) == 0
        assert bt.slot_index(19, 15) == 1
        assert bt.slot_index(23, 30) == 18
        assert bt.slot_index(0, 0) == 20
        assert bt.slot_index(4, 45) == 39

    def test_out_of_window(self) -> None:
        assert bt.slot_index(5, 0) is None      # 窓終端(exclusive)
        assert bt.slot_index(18, 45) is None     # 窓始端の直前
        assert bt.slot_index(12, 0) is None       # 昼


class TestPercentile:
    def test_single_and_uniform(self) -> None:
        assert bt.percentile([5.0], 10) == 5.0
        assert bt.percentile([2.0, 2.0, 2.0], 90) == 2.0

    def test_linear_interpolation(self) -> None:
        vals = [0.0, 10.0]
        assert bt.percentile(vals, 10) == pytest.approx(1.0)
        assert bt.percentile(vals, 90) == pytest.approx(9.0)

    def test_empty(self) -> None:
        assert bt.percentile([], 50) == 0.0


# --------------------------------------------------------------------------- #
# build_night_curves
# --------------------------------------------------------------------------- #
class TestBuildNightCurves:
    def test_grouping_mean_and_window(self) -> None:
        rows = [
            {"ts": "2026-05-02T19:00:00+09:00", "total": 10, "men": 6, "women": 4},
            {"ts": "2026-05-02T19:05:00+09:00", "total": 20, "men": 12, "women": 8},
            {"ts": "2026-05-03T02:00:00+09:00", "total": 5, "men": 3, "women": 2},
            {"ts": "2026-05-03T06:00:00+09:00", "total": 99},  # 窓外(06:00)→除外
        ]
        nights = bt.build_night_curves(rows)
        # 06:00 は夜セッション外なので新しい夜 5/3 は生まれない
        assert set(nights.keys()) == {date(2026, 5, 2)}
        n = nights[date(2026, 5, 2)]
        assert n[0]["total"] == pytest.approx(15.0)   # (10+20)/2
        assert n[0]["men"] == pytest.approx(9.0)
        assert n[28]["total"] == pytest.approx(5.0)   # 02:00 → 前夜 5/2 の slot 28

    def test_total_from_men_women_when_missing(self) -> None:
        rows = [{"ts": "2026-05-02T20:00:00+09:00", "men": 7, "women": 3}]
        nights = bt.build_night_curves(rows)
        assert nights[date(2026, 5, 2)][4]["total"] == pytest.approx(10.0)


# --------------------------------------------------------------------------- #
# build_template
# --------------------------------------------------------------------------- #
class TestBuildTemplate:
    def test_shape_normalized_to_one(self) -> None:
        totals = [float(i + 1) for i in range(bt.SLOTS)]  # 1..40
        nights = [(date(2026, 4, 20 - k % 10), make_night(totals)) for k in range(6)]
        tmpl = bt.build_template(nights)
        assert tmpl is not None
        assert sum(tmpl["shape"]) == pytest.approx(1.0, abs=1e-6)
        s = sum(totals)
        assert tmpl["shape"][0] == pytest.approx(1.0 / s, abs=1e-6)
        assert tmpl["shape"][-1] == pytest.approx(40.0 / s, abs=1e-6)

    def test_men_ratio_and_fallback(self) -> None:
        totals = [10.0] * bt.SLOTS
        nights = [(date(2026, 4, 20), make_night(totals, men_frac=0.7))]
        tmpl = bt.build_template(nights)
        assert tmpl is not None
        assert all(r == pytest.approx(0.7, abs=1e-6) for r in tmpl["men_ratio"])

    def test_scale_ref_is_median_of_recent_six(self) -> None:
        sums = [100, 90, 80, 70, 60, 50, 40, 30]  # newest-first
        nights = [(date(2026, 4, 28 - i), flat_night(s)) for i, s in enumerate(sums)]
        tmpl = bt.build_template(nights)
        assert tmpl is not None
        assert tmpl["n_nights"] == 8
        # 直近6 = [100,90,80,70,60,50] の median = (80+70)/2 = 75
        assert tmpl["scale_ref"] == pytest.approx(75.0)

    def test_partial_nights_excluded(self) -> None:
        good = make_night([10.0] * bt.SLOTS)
        partial = {i: {"total": 10.0} for i in range(5)}  # 5 slots < MIN_SLOTS_PER_NIGHT
        tmpl = bt.build_template([(date(2026, 4, 20), good), (date(2026, 4, 19), partial)])
        assert tmpl is not None
        assert tmpl["n_nights"] == 1

    def test_empty_returns_none(self) -> None:
        assert bt.build_template([]) is None
        zero = {i: {"total": 0.0} for i in range(bt.SLOTS)}  # 夜合計0 → 除外
        assert bt.build_template([(date(2026, 4, 20), zero)]) is None

    def test_p10_p90_band(self) -> None:
        # 同一 slot に 0.02 と 0.03 が半々 → p10≈0.02付近, p90≈0.03付近
        nights = []
        for k in range(4):
            totals = [0.0] * bt.SLOTS
            hi = k % 2 == 0
            for i in range(bt.SLOTS):
                totals[i] = 30.0 if hi else 20.0
            nights.append((date(2026, 4, 20 - k), make_night(totals)))
        tmpl = bt.build_template(nights)
        assert tmpl is not None
        for i in range(bt.SLOTS):
            assert tmpl["p10"][i] <= tmpl["p90"][i]


# --------------------------------------------------------------------------- #
# reference_nights (special-block exclusion)
# --------------------------------------------------------------------------- #
class TestReferenceNights:
    def test_special_blocks_excluded(self) -> None:
        nights = {
            date(2026, 4, 11): make_night([10.0] * bt.SLOTS),  # 通常(土)
            date(2025, 8, 14): make_night([10.0] * bt.SLOTS),  # お盆 → 除外
            date(2026, 5, 4): make_night([10.0] * bt.SLOTS),   # GW → 除外
            date(2026, 1, 1): make_night([10.0] * bt.SLOTS),   # 年末年始 → 除外
        }
        ref = bt.reference_nights(nights)
        assert [nd for nd, _ in ref] == [date(2026, 4, 11)]


# --------------------------------------------------------------------------- #
# build_store_templates (fallback ladder)
# --------------------------------------------------------------------------- #
class TestBuildStoreTemplates:
    TODAY = date(2026, 4, 30)

    def _L_nights(self) -> list:
        # 平日通常(月〜木) → L。8 夜。
        days = [13, 14, 15, 16, 20, 21, 22, 23]
        return [(date(2026, 4, d), flat_night(100.0)) for d in days]

    def test_all_types_present(self) -> None:
        nights = self._L_nights()
        nights += [(date(2026, 4, d), flat_night(120.0)) for d in (12, 19, 26)]  # 日曜×3 (M)
        nights += [(date(2026, 4, d), flat_night(360.0)) for d in (10, 11, 17, 18)]  # 金土×4 (H)
        out = bt.build_store_templates(nights, self.TODAY)
        assert out is not None
        assert set(out.keys()) == {"L", "M", "H"}
        assert out["L"]["fallback"] is None
        assert out["H"]["fallback"] is None
        assert sum(out["L"]["shape"]) == pytest.approx(1.0, abs=1e-6)

    def test_M_borrows_L_shape_with_M_scale(self) -> None:
        # M 夜がちょうど 3（>=MIN_SCALE_SAMPLE, <MIN_NIGHTS）→ L シェイプ + M スケール
        nights = self._L_nights()
        nights += [(date(2026, 4, d), flat_night(120.0)) for d in (12, 19, 26)]  # 日曜×3
        out = bt.build_store_templates(nights, self.TODAY)
        assert out is not None
        assert out["M"]["fallback"] == "L_shape+M_scale"
        assert out["M"]["shape"] == out["L"]["shape"]
        assert out["M"]["n_nights"] == 3
        assert out["M"]["scale_ref"] == pytest.approx(120.0)

    def test_M_borrows_L_shape_with_sunday_factor(self) -> None:
        # M 夜が 0（<MIN_SCALE_SAMPLE）→ L スケール × 1.20
        nights = self._L_nights()
        out = bt.build_store_templates(nights, self.TODAY)
        assert out is not None
        assert out["M"]["fallback"] == "L_shape+L_scale_x1.2"
        assert out["M"]["scale_ref"] == pytest.approx(out["L"]["scale_ref"] * 1.20)

    def test_H_falls_back_to_all_type(self) -> None:
        # H 夜が薄い（0）→ all_type シェイプ+スケール（never empty）
        nights = self._L_nights()
        out = bt.build_store_templates(nights, self.TODAY)
        assert out is not None
        assert out["H"]["fallback"] == "all_type"
        assert out["H"]["n_nights"] >= 1

    def test_empty_returns_none(self) -> None:
        assert bt.build_store_templates([], self.TODAY) is None


# --------------------------------------------------------------------------- #
# v2.1 レバー2: 帯 k 拡幅の算術（純関数）
# --------------------------------------------------------------------------- #
class TestWidenBand:
    def test_k_one_is_noop(self) -> None:
        shape = [0.10, 0.20, 0.05]
        p10 = [0.05, 0.15, 0.01]
        p90 = [0.20, 0.30, 0.09]
        p10w, p90w = bt.widen_band(shape, p10, p90, 1.0)
        assert p10w == pytest.approx(p10)
        assert p90w == pytest.approx(p90)

    def test_p50_unchanged_and_symmetric_widen(self) -> None:
        # shape(=p50) は関数の出力に含めず、拡幅は p50 を軸に対称スケール。
        shape = [0.10]
        p10 = [0.05]
        p90 = [0.20]
        p10w, p90w = bt.widen_band(shape, p10, p90, 1.7)
        assert p10w[0] == pytest.approx(0.10 - 1.7 * (0.10 - 0.05))  # 0.015
        assert p90w[0] == pytest.approx(0.10 + 1.7 * (0.20 - 0.10))  # 0.27

    def test_floor_at_zero(self) -> None:
        # k が大きく p10' が負になるケースは 0 でクリップ。p90' は青天井のまま。
        shape = [0.10]
        p10 = [0.09]
        p90 = [0.11]
        p10w, p90w = bt.widen_band(shape, p10, p90, 20.0)
        assert p10w[0] == 0.0
        assert p90w[0] == pytest.approx(0.10 + 20.0 * 0.01)

    def test_apply_band_calibration_in_place(self) -> None:
        totals = [10.0] * bt.SLOTS
        nights = [(date(2026, 4, 20 - k), make_night(totals)) for k in range(6)]
        tmpl = bt.build_store_templates(nights, date(2026, 4, 30))
        assert tmpl is not None
        before_shape = list(tmpl["L"]["shape"])
        bt.apply_band_calibration(tmpl, 1.0)  # k=1 → p10/p90 据え置き・shape 不変
        assert tmpl["L"]["shape"] == before_shape


# --------------------------------------------------------------------------- #
# v2.1 レバー2: 帯 k の自動再校正ルール（純関数）
# --------------------------------------------------------------------------- #
class TestRecalibrateK:
    def test_default_when_no_prev_no_data(self) -> None:
        assert bt.recalibrate_k(None, []) == bt.DEFAULT_BAND_K

    def test_keeps_prev_when_no_data(self) -> None:
        assert bt.recalibrate_k(1.5, []) == 1.5

    def test_low_coverage_widens(self) -> None:
        # 平均 0.71 < 0.78 → +0.1
        assert bt.recalibrate_k(1.7, [0.70, 0.72]) == pytest.approx(1.8)

    def test_high_coverage_narrows(self) -> None:
        # 平均 0.91 > 0.86 → -0.1
        assert bt.recalibrate_k(1.7, [0.90, 0.92]) == pytest.approx(1.6)

    def test_deadband_no_change(self) -> None:
        # 0.78 <= mean <= 0.86 は据え置き
        assert bt.recalibrate_k(1.7, [0.80, 0.82]) == pytest.approx(1.7)

    def test_boundary_low_is_deadband(self) -> None:
        # ちょうど 0.78 は「< 0.78」に該当しない → 据え置き
        assert bt.recalibrate_k(1.7, [0.78]) == pytest.approx(1.7)

    def test_boundary_high_is_deadband(self) -> None:
        # ちょうど 0.86 は「> 0.86」に該当しない → 据え置き
        assert bt.recalibrate_k(1.7, [0.86]) == pytest.approx(1.7)

    def test_clamp_max(self) -> None:
        # 2.2 から更に広げようとしても上限 2.2
        assert bt.recalibrate_k(2.2, [0.10]) == pytest.approx(bt.BAND_K_MAX)

    def test_clamp_min(self) -> None:
        # 1.0 から更に狭めようとしても下限 1.0
        assert bt.recalibrate_k(1.0, [0.99]) == pytest.approx(bt.BAND_K_MIN)


# --------------------------------------------------------------------------- #
# v2.1 レバー1: blend50 の特徴量構築（同タイプ直近・≥3 ガード）
# --------------------------------------------------------------------------- #
class TestScaleFeatures:
    def test_recents_use_last_six_same_type(self) -> None:
        prior = [100.0, 200.0, 300.0, 400.0, 500.0, 600.0, 700.0]  # 古い順
        feat = bt._scale_features("ol_shibuya", "H", prior)
        # 直近6 = [200..700] → median 450, mean 450, last1 700
        assert feat["store"] == "ol_shibuya"
        assert feat["night_type"] == "H"
        assert feat["recent_median6"] == pytest.approx(450.0)
        assert feat["recent_mean6"] == pytest.approx(450.0)
        assert feat["recent_last1"] == pytest.approx(700.0)

    def test_empty_prior_is_nan(self) -> None:
        import math

        feat = bt._scale_features("x", "L", [])
        assert math.isnan(feat["recent_median6"])
        assert math.isnan(feat["recent_mean6"])
        assert math.isnan(feat["recent_last1"])


class TestBuildScaleTrainingRows:
    def _samples(self, types: list[str], base: float = 100.0) -> list[dict]:
        # 古い順に types を並べ、夜合計は index に比例させて可変にする。
        return [
            {"date": date(2026, 4, 1) + timedelta(days=i), "night_type": t, "total": base + i}
            for i, t in enumerate(types)
        ]

    def test_min_three_prior_same_type_guard(self) -> None:
        # H が 5 夜連続。行が立つのは 4 夜目以降（=同タイプ過去夜 >=3）→ 2 行。
        samples = self._samples(["H", "H", "H", "H", "H"])
        rows = bt.build_scale_training_rows({"s": samples})
        assert len(rows) == 2
        assert all(r["night_type"] == "H" for r in rows)

    def test_recents_are_same_type_only(self) -> None:
        # L,L,L,H,H,H,H → H 行は H の過去夜だけを recents に使う（L は混ぜない）。
        samples = self._samples(["L", "L", "L", "H", "H", "H", "H"])
        rows = bt.build_scale_training_rows({"s": samples})
        # H の過去夜が 3 に達するのは 7 番目(index6)の H だけ → H 行は 1 行。
        h_rows = [r for r in rows if r["night_type"] == "H"]
        assert len(h_rows) == 1
        # index 3,4,5 の H(total=103,104,105)が recents → median 104, last1 105
        assert h_rows[0]["recent_median6"] == pytest.approx(104.0)
        assert h_rows[0]["recent_last1"] == pytest.approx(105.0)
        assert h_rows[0]["target"] == pytest.approx(106.0)  # index6 の total

    def test_no_leak_uses_only_prior_nights(self) -> None:
        # 各行の recents は「その夜より前」だけ。最後の L 夜(target)は recents に入らない。
        samples = self._samples(["L", "L", "L", "L"])
        rows = bt.build_scale_training_rows({"s": samples})
        assert len(rows) == 1
        r = rows[0]
        assert r["recent_last1"] == pytest.approx(102.0)  # index2、target=index3(103) は除外
        assert r["target"] == pytest.approx(103.0)


class TestNightScaleSamples:
    def test_valid_nights_only_and_chronological(self) -> None:
        good = make_night([10.0] * bt.SLOTS)                     # 40 slots, sum>0
        partial = {i: {"total": 10.0} for i in range(5)}         # 5 slots < MIN_SLOTS_PER_NIGHT
        zero = {i: {"total": 0.0} for i in range(bt.SLOTS)}      # sum 0
        ref = [
            (date(2026, 4, 20), good),
            (date(2026, 4, 19), partial),
            (date(2026, 4, 18), zero),
        ]
        samples = bt._night_scale_samples(ref)
        assert [s["date"] for s in samples] == [date(2026, 4, 20)]
        assert samples[0]["total"] == pytest.approx(400.0)  # 40 * 10
        assert samples[0]["night_type"] in ("L", "M", "H")
