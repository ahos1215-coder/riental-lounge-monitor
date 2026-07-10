import { describe, expect, it } from "vitest";
import {
  COUNT_AXIS_ID,
  PERCENT_AXIS_ID,
  axisIdForBrand,
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
