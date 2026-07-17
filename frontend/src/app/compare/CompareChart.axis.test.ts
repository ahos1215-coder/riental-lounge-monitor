import { describe, expect, it } from "vitest";
import {
  COUNT_AXIS_ID,
  PERCENT_AXIS_ID,
  axisIdForBrand,
  formatCompareTooltipValue,
  resolveCompareAxes,
} from "./CompareChart";

describe("resolveCompareAxes", () => {
  it("人数(オリエンタル)と%(相席屋)が混在したら2軸に分ける", () => {
    const axes = resolveCompareAxes(["oriental", "aisekiya"]);
    expect(axes).toEqual({
      showCountAxis: true,
      showPercentAxis: true,
      dual: true,
    });
  });

  it("オリエンタルのみなら人数の単一軸（%軸は出さない）", () => {
    const axes = resolveCompareAxes(["oriental", "jis"]);
    expect(axes.showCountAxis).toBe(true);
    expect(axes.showPercentAxis).toBe(false);
    expect(axes.dual).toBe(false);
  });

  it("相席屋のみなら%の単一軸（人数軸は出さない）", () => {
    const axes = resolveCompareAxes(["aisekiya", "aisekiya"]);
    expect(axes.showCountAxis).toBe(false);
    expect(axes.showPercentAxis).toBe(true);
    expect(axes.dual).toBe(false);
  });

  it("空（データ未到着）でも空軸を出さず人数の単一軸にフォールバック", () => {
    const axes = resolveCompareAxes([]);
    expect(axes).toEqual({
      showCountAxis: true,
      showPercentAxis: false,
      dual: false,
    });
  });
});

describe("axisIdForBrand", () => {
  it("相席屋は%軸、オリエンタル/JISは人数軸に割り当てる", () => {
    expect(axisIdForBrand("aisekiya")).toBe(PERCENT_AXIS_ID);
    expect(axisIdForBrand("oriental")).toBe(COUNT_AXIS_ID);
    expect(axisIdForBrand("jis")).toBe(COUNT_AXIS_ID);
  });
});

describe("formatCompareTooltipValue — rank15 raw-float tooltip fix", () => {
  it("rounds a long floating-point value to an integer before appending the unit", () => {
    // 本番で確認された生値: "26.111711784503775人"
    expect(formatCompareTooltipValue(26.111711784503775, "人")).toBe("26人");
  });

  it("rounds a percent value the same way", () => {
    expect(formatCompareTooltipValue(63.499999999999, "%")).toBe("63%");
  });

  it("rounds .5 up (standard Math.round behavior)", () => {
    expect(formatCompareTooltipValue(10.5, "人")).toBe("11人");
  });

  it("passes through already-integer values unchanged (aside from unit)", () => {
    expect(formatCompareTooltipValue(42, "人")).toBe("42人");
  });

  it("falls back to passing the raw value through for non-numeric input (defensive)", () => {
    expect(formatCompareTooltipValue("N/A", "人")).toBe("N/A人");
  });
});
