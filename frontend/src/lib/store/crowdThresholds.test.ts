// frontend/src/lib/store/crowdThresholds.test.ts
//
// 番犬（C-08）: 120/80 の絶対閾値は store 一覧と LINE 下書きで同じ値・別文言。
// 集約後もラベル文言が 1 文字も変わっていないことを固定する。
import { describe, expect, it } from "vitest";
import {
  CROWD_ABS_BUSY_MIN,
  CROWD_ABS_MODERATE_MIN,
  crowdTierFromPeakTotal,
} from "./crowdThresholds";
import { crowdLabelFromPred } from "@/app/stores/storesListHelpers";

describe("crowdThresholds", () => {
  it("閾値は 120 / 80（既存値のまま）", () => {
    expect(CROWD_ABS_BUSY_MIN).toBe(120);
    expect(CROWD_ABS_MODERATE_MIN).toBe(80);
  });

  it("境界で段階が切り替わる", () => {
    expect(crowdTierFromPeakTotal(0)).toBe("quiet");
    expect(crowdTierFromPeakTotal(79)).toBe("quiet");
    expect(crowdTierFromPeakTotal(80)).toBe("moderate");
    expect(crowdTierFromPeakTotal(119)).toBe("moderate");
    expect(crowdTierFromPeakTotal(120)).toBe("busy");
  });

  it("店舗一覧のラベル文言は旧実装と同一", () => {
    const legacy = (maxPred: number): string => {
      if (maxPred >= 120) return "混雑";
      if (maxPred >= 80) return "ほどよい";
      return "空いている";
    };
    for (const v of [0, 1, 79, 80, 81, 119, 120, 121, 999]) {
      expect(crowdLabelFromPred(v), String(v)).toBe(legacy(v));
    }
  });
});
