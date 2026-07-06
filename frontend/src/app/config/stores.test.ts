import { describe, expect, it } from "vitest";

import {
  buildStoreFullName,
  distanceKm,
  isPercentCrowdBrand,
  seatFullnessPercent,
  type StoreMeta,
} from "./stores";

describe("seatFullnessPercent", () => {
  it("computes the rounded percent for a normal count/capacity pair", () => {
    expect(seatFullnessPercent(20, 38)).toBe(53);
  });

  it("returns 0 for a zero count", () => {
    expect(seatFullnessPercent(0, 38)).toBe(0);
  });

  it("clamps counts above capacity to 100", () => {
    expect(seatFullnessPercent(100, 38)).toBe(100);
  });

  it("clamps negative counts to 0", () => {
    expect(seatFullnessPercent(-5, 38)).toBe(0);
  });

  it("returns null when capacity is null", () => {
    expect(seatFullnessPercent(5, null)).toBeNull();
  });

  it("returns null when capacity is 0", () => {
    expect(seatFullnessPercent(5, 0)).toBeNull();
  });
});

describe("isPercentCrowdBrand", () => {
  it("is true for aisekiya", () => {
    expect(isPercentCrowdBrand("aisekiya")).toBe(true);
  });

  it("is false for oriental", () => {
    expect(isPercentCrowdBrand("oriental")).toBe(false);
  });

  it("is false for jis", () => {
    expect(isPercentCrowdBrand("jis")).toBe(false);
  });
});

describe("distanceKm", () => {
  it("returns ~0 for the same point", () => {
    const point = { lat: 35.68, lon: 139.77 };
    const result = distanceKm(point, point);
    expect(result).not.toBeNull();
    expect(result as number).toBeCloseTo(0, 3);
  });

  it("returns a plausible distance between Tokyo and Osaka", () => {
    const tokyo = { lat: 35.68, lon: 139.77 };
    const osaka = { lat: 34.69, lon: 135.5 };
    const result = distanceKm(tokyo, osaka);
    expect(result).not.toBeNull();
    expect(result as number).toBeGreaterThan(380);
    expect(result as number).toBeLessThan(430);
  });

  it("is symmetric", () => {
    const tokyo = { lat: 35.68, lon: 139.77 };
    const osaka = { lat: 34.69, lon: 135.5 };
    const ab = distanceKm(tokyo, osaka) as number;
    const ba = distanceKm(osaka, tokyo) as number;
    expect(ab).toBeCloseTo(ba, 9);
  });

  it("returns null when either point has a null lat/lon", () => {
    const tokyo = { lat: 35.68, lon: 139.77 };
    const unknown = { lat: null, lon: null };
    expect(distanceKm(tokyo, unknown)).toBeNull();
    expect(distanceKm(unknown, tokyo)).toBeNull();
  });
});

describe("buildStoreFullName", () => {
  const baseMeta: StoreMeta = {
    slug: "shibuya",
    storeId: "ay_shibuya",
    label: "渋谷",
    areaLabel: "渋谷",
    regionLabel: "関東",
    mapsQueryBase: "",
    brand: "aisekiya",
    capacity: 38,
    lat: null,
    lon: null,
    officialUrl: null,
  };

  it("prefixes aisekiya stores with 相席屋", () => {
    expect(buildStoreFullName({ ...baseMeta, brand: "aisekiya", label: "渋谷" })).toBe(
      "相席屋 渋谷",
    );
  });

  it("prefixes oriental stores with オリエンタルラウンジ", () => {
    expect(
      buildStoreFullName({ ...baseMeta, brand: "oriental", label: "渋谷", capacity: null }),
    ).toBe("オリエンタルラウンジ 渋谷");
  });
});
