import { describe, expect, it } from "vitest";

import { resolveNightsWindow, resolveStoreComparison } from "./forecastAccuracy";

describe("resolveNightsWindow", () => {
  it("falls back to mae_7d/nights_count while mae_30d is null (n<30)", () => {
    const win = resolveNightsWindow({ mae_30d: null, mae_7d: 11.87, nights_count: 7 });
    expect(win).toEqual({ nights: 7, label: "直近7夜", matured: false });
  });

  it("marks matured once mae_30d is populated (n>=30)", () => {
    const win = resolveNightsWindow({ mae_30d: 9.8, mae_7d: 8.1, nights_count: 30 });
    expect(win).toEqual({ nights: 30, label: "直近30夜", matured: true });
  });

  it("never fabricates a 30-night label when only 7 nights exist", () => {
    const win = resolveNightsWindow({ mae_30d: null, mae_7d: 11.87, nights_count: 7 });
    expect(win?.label).not.toContain("30");
  });

  it("returns null when live data is absent", () => {
    expect(resolveNightsWindow(null)).toBeNull();
    expect(resolveNightsWindow(undefined)).toBeNull();
  });

  it("returns null when nights_count is 0 or missing", () => {
    expect(resolveNightsWindow({ mae_30d: null, mae_7d: 11.87, nights_count: 0 })).toBeNull();
    expect(resolveNightsWindow({ mae_30d: null, mae_7d: 11.87, nights_count: null })).toBeNull();
  });

  it("returns null when neither mae figure exists yet", () => {
    expect(resolveNightsWindow({ mae_30d: null, mae_7d: null, nights_count: 7 })).toBeNull();
  });
});

describe("resolveStoreComparison", () => {
  it("reports worse=true when ML underperforms this store's own baseline", () => {
    // ay_chiba 実データ相当: ML 14.74 vs 基準 1.43
    const cmp = resolveStoreComparison(14.74, 1.43);
    expect(cmp).toEqual({ mae: 14.74, baseline: 1.43, worse: true });
  });

  it("reports worse=false when ML beats this store's own baseline", () => {
    // ay_yokohama 実データ相当: ML 3.99 vs 基準 7.26
    const cmp = resolveStoreComparison(3.99, 7.26);
    expect(cmp).toEqual({ mae: 3.99, baseline: 7.26, worse: false });
  });

  it("returns null when either value is missing", () => {
    expect(resolveStoreComparison(null, 1.43)).toBeNull();
    expect(resolveStoreComparison(14.74, undefined)).toBeNull();
    expect(resolveStoreComparison(undefined, undefined)).toBeNull();
  });

  it("returns null on non-finite input", () => {
    expect(resolveStoreComparison(NaN, 1.43)).toBeNull();
    expect(resolveStoreComparison(14.74, Infinity)).toBeNull();
  });
});
