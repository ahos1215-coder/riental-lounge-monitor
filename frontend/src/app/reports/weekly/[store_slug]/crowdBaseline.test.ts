import { describe, expect, it } from "vitest";

import { buildCrowdBaselineDisplay } from "./crowdBaseline";

describe("buildCrowdBaselineDisplay（週報「混み具合の基準」）", () => {
  it("オリエンタルは従来どおり人数表示（整数・単位は人）", () => {
    const r = buildCrowdBaselineDisplay({ brand: "oriental", capacity: null }, 42.6);
    expect(r.value).toBe("43");
    expect(r.unit).toBe(" 人");
    expect(r.fallbackHint).toContain("人数");
  });

  it("相席屋は人数を出さず席の埋まり具合(%)に換算する", () => {
    // ay_shibuya: capacity=38（片性別）→ 店舗全体 76 席。38 人 = 50%
    const r = buildCrowdBaselineDisplay({ brand: "aisekiya", capacity: 38 }, 38);
    expect(r.value).toBe("50");
    expect(r.unit).toBe("%");
    expect(r.fallbackHint).not.toContain("人数");
  });

  it("相席屋の%換算は店舗ページと同じ式（合計人数 / (capacity*2)）", () => {
    // ay_chiba: capacity=44 → 88 席。66 人 = 75%
    expect(buildCrowdBaselineDisplay({ brand: "aisekiya", capacity: 44 }, 66).value).toBe("75");
  });

  it("相席屋の%は 0-100 にクランプされる", () => {
    expect(buildCrowdBaselineDisplay({ brand: "aisekiya", capacity: 28 }, 999).value).toBe("100");
    expect(buildCrowdBaselineDisplay({ brand: "aisekiya", capacity: 28 }, 0).value).toBe("0");
  });

  it("capacity が無い相席屋（想定外データ）は人数表示にフォールバックする", () => {
    const r = buildCrowdBaselineDisplay({ brand: "aisekiya", capacity: null }, 20);
    expect(r.value).toBe("20");
    expect(r.unit).toBe(" 人");
  });

  it("数値が無いときは単位を保ったまま '-'", () => {
    expect(buildCrowdBaselineDisplay({ brand: "oriental", capacity: null }, undefined)).toEqual({
      value: "-",
      unit: " 人",
      fallbackHint: "この人数以上なら「混んでいる」目安",
    });
    expect(buildCrowdBaselineDisplay({ brand: "aisekiya", capacity: 30 }, "x").value).toBe("-");
    expect(buildCrowdBaselineDisplay({ brand: "aisekiya", capacity: 30 }, NaN).value).toBe("-");
  });
});
