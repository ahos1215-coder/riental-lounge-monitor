import { describe, expect, it } from "vitest";
import data from "@/data/storeTrends.generated.json";
import { STORES } from "@/app/config/stores";
import { HEATMAP_HOURS } from "./storeTrends";
import { getStoreTrendEntry } from "./storeTrendsData";

type Entry = {
  weeks: string[];
  periodStart: string;
  periodEnd: string;
  cells: { d: number; h: number; o: number; f: number; n: number }[];
};

describe("storeTrends.generated.json", () => {
  const stores = data.stores as unknown as Record<string, Entry>;
  const ymd = /^\d{4}-\d{2}-\d{2}$/;

  it("schemaVersion 1", () => {
    expect(data.schemaVersion).toBe(1);
  });
  it("キーは既知の店舗 slug のみ", () => {
    const known = new Set(STORES.map((s) => s.slug));
    for (const k of Object.keys(stores)) expect(known.has(k), k).toBe(true);
    expect(Object.keys(stores).length).toBeGreaterThan(0);
  });
  it("各エントリの形と値域", () => {
    for (const [slug, e] of Object.entries(stores)) {
      expect(e.weeks.length, slug).toBeGreaterThanOrEqual(1);
      for (const w of e.weeks) expect(w).toMatch(ymd);
      expect(e.periodStart).toMatch(ymd);
      expect(e.periodEnd).toMatch(ymd);
      expect(e.cells.length).toBeGreaterThan(0);
      for (const c of e.cells) {
        expect(c.d).toBeGreaterThanOrEqual(0);
        expect(c.d).toBeLessThanOrEqual(6);
        expect(HEATMAP_HOURS).toContain(c.h);
        expect(c.o).toBeGreaterThanOrEqual(0);
        expect(c.o).toBeLessThanOrEqual(1);
        expect(c.f).toBeGreaterThanOrEqual(0);
        expect(c.f).toBeLessThanOrEqual(1);
        expect(c.n).toBeGreaterThan(0);
      }
    }
  });
  it("getStoreTrendEntry は未知 slug で null", () => {
    expect(getStoreTrendEntry("no_such_store")).toBeNull();
    expect(getStoreTrendEntry("__proto__")).toBeNull();
  });
});
