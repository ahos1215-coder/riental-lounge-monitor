import { describe, expect, it } from "vitest";

import {
  GRADE_HIGH_MAX_RELATIVE,
  GRADE_STANDARD_MAX_RELATIVE,
  resolveAccuracyGrade,
  resolveNightsWindow,
  resolveStoreComparison,
} from "./forecastAccuracy";

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

describe("resolveAccuracyGrade", () => {
  // 実データ (2026-07-09) の相対誤差 = live_mae / 想定夜間来客数(予測総数平均):
  //   shibuya 11.78/44.8=0.26, ebisu 14.74/57.9=0.25, utsunomiya 2.39/3.5=0.69,
  //   kashiwa 6.99/11.8=0.59（かつ live 6.99 > baseline 4.02 -> beatsBaseline=false）。

  it("小規模店の高絶対MAE・悪い相対 -> 高精度にしない（逆転バグの本丸）", () => {
    // utsunomiya: 絶対 MAE は小さい(2.39)が、規模比では 69% と悪い -> 高精度にしない。
    const g = resolveAccuracyGrade({ hasLive: true, relativeMae: 0.69, beatsBaseline: true });
    expect(g).not.toBe("high");
    expect(g).toBe("reference"); // 0.69 >= 0.50
  });

  it("大規模店の低相対誤差 -> 高精度（絶対 MAE が大きくても）", () => {
    // shibuya: 絶対 MAE 11.78 は大きいが規模比 26% -> 高精度。
    expect(resolveAccuracyGrade({ hasLive: true, relativeMae: 0.26, beatsBaseline: true })).toBe("high");
    // ebisu: 規模比 25% -> 高精度。
    expect(resolveAccuracyGrade({ hasLive: true, relativeMae: 0.25, beatsBaseline: true })).toBe("high");
  });

  it("ナイーブ基準に負けている店は相対誤差に関わらず参考値に丸める（kashiwa）", () => {
    // kashiwa: relative 0.59 でも beatsBaseline=false -> 参考値（絶対 MAE でも「標準」にしない）。
    expect(resolveAccuracyGrade({ hasLive: true, relativeMae: 0.59, beatsBaseline: false })).toBe("reference");
    // たとえ相対誤差が極小でも、基準に負けていれば高精度/標準にはならない。
    expect(resolveAccuracyGrade({ hasLive: true, relativeMae: 0.05, beatsBaseline: false })).toBe("reference");
  });

  it("相対誤差のしきい値（境界は排他）", () => {
    // < 0.30 -> high, < 0.50 -> standard, それ以上 -> reference
    expect(resolveAccuracyGrade({ hasLive: true, relativeMae: 0.29, beatsBaseline: true })).toBe("high");
    expect(resolveAccuracyGrade({ hasLive: true, relativeMae: GRADE_HIGH_MAX_RELATIVE, beatsBaseline: true })).toBe("standard");
    expect(resolveAccuracyGrade({ hasLive: true, relativeMae: 0.49, beatsBaseline: true })).toBe("standard");
    expect(resolveAccuracyGrade({ hasLive: true, relativeMae: GRADE_STANDARD_MAX_RELATIVE, beatsBaseline: true })).toBe("reference");
  });

  it("実測が無い（holdout フォールバック）-> 参考値", () => {
    expect(resolveAccuracyGrade({ hasLive: false, relativeMae: 0.1, beatsBaseline: true })).toBe("reference");
    expect(resolveAccuracyGrade({ hasLive: false })).toBe("reference");
  });

  it("相対誤差が無いが基準に勝っている -> 中位の標準に留める", () => {
    expect(resolveAccuracyGrade({ hasLive: true, relativeMae: null, beatsBaseline: true })).toBe("standard");
  });

  it("相対誤差も基準情報も無い（実測はある）-> 参考値", () => {
    expect(resolveAccuracyGrade({ hasLive: true, relativeMae: null, beatsBaseline: null })).toBe("reference");
  });

  it("非有限の相対誤差は無視して基準比較にフォールバック", () => {
    expect(resolveAccuracyGrade({ hasLive: true, relativeMae: NaN, beatsBaseline: true })).toBe("standard");
    expect(resolveAccuracyGrade({ hasLive: true, relativeMae: Infinity, beatsBaseline: false })).toBe("reference");
  });
});
