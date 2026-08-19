// frontend/src/lib/store/nightHourlyRollup.test.ts
//
// 番犬（C-12）: 時間帯別ロールアップは店舗 SSR（ssrSummary）とエリア（areaLiveSummary）に
// 二重実装されていた。共通化後も両方の旧実装と同じ並び・同じ代表値になることを固定する。
import { describe, expect, it } from "vitest";
import { MIN_HOURLY_BUCKETS, rollUpByNightHour } from "./nightHourlyRollup";
import { rollUpHourlyActuals } from "./ssrSummary";
import type { TimeSeriesPoint } from "@/lib/forecast/types";

/** 旧 ssrSummary.rollUpHourlyActuals（写経） */
function legacyRollUpHourlyActuals(
  series: readonly TimeSeriesPoint[],
): { hour: string; total: number }[] {
  const toNonNegativeInt = (value: unknown): number => {
    const n = Number(value ?? 0);
    if (!Number.isFinite(n)) return 0;
    return Math.max(0, Math.round(n));
  };
  const byHour = new Map<string, number>();
  for (const p of series) {
    if (p.menActual === null && p.womenActual === null) continue;
    const m = /^(\d{2}):\d{2}$/.exec(p.label ?? "");
    if (!m) continue;
    const total = toNonNegativeInt(p.menActual ?? 0) + toNonNegativeInt(p.womenActual ?? 0);
    if (total <= 0) continue;
    const prev = byHour.get(m[1]);
    if (prev === undefined || total > prev) byHour.set(m[1], total);
  }
  const nightOrder = (hh: string): number => {
    const h = Number(hh);
    return h >= 19 ? h : h + 24;
  };
  return Array.from(byHour.entries())
    .sort((a, b) => nightOrder(a[0]) - nightOrder(b[0]))
    .map(([hour, total]) => ({ hour, total }));
}

/** 旧 areaLiveSummary の byHour ループ（写経） */
function legacyAreaBuckets(rows: { hour: number | null; total: number }[]): [number, number][] {
  const byHour = new Map<number, number>();
  for (const r of rows) {
    if (r.hour === null) continue;
    const t = r.total;
    if (t <= 0) continue;
    const prev = byHour.get(r.hour);
    if (prev === undefined || t > prev) byHour.set(r.hour, t);
  }
  const nightOrder = (h: number) => (h >= 19 ? h : h + 24);
  return [...byHour.entries()].sort((a, b) => nightOrder(a[0]) - nightOrder(b[0]));
}

function pt(label: string, menActual: number | null, womenActual: number | null): TimeSeriesPoint {
  return { label, menActual, womenActual, menForecast: null, womenForecast: null };
}

const SERIES: TimeSeriesPoint[] = [
  pt("19:05", 3, 2),
  pt("19:35", 8, 6), // 19時の代表は 14
  pt("20:00", 0, 0), // 0 は捨てる
  pt("23:15", 20, 18),
  pt("00:10", 15, 12), // 夜順で 23時の後
  pt("01:00", null, null), // 実測なしは無視
  pt("bad-label", 5, 5), // ラベル不正は無視
  pt("05:00", 1, 0),
];

describe("rollUpByNightHour — 旧2実装との等価（番犬）", () => {
  it("最小バケット数は 2（両ページ共通の既存値）", () => {
    expect(MIN_HOURLY_BUCKETS).toBe(2);
  });

  it("ssrSummary.rollUpHourlyActuals は旧実装と同じ（2桁文字列の hour・夜順）", () => {
    expect(rollUpHourlyActuals(SERIES)).toEqual(legacyRollUpHourlyActuals(SERIES));
    expect(rollUpHourlyActuals(SERIES)).toEqual([
      { hour: "19", total: 14 },
      { hour: "23", total: 38 },
      { hour: "00", total: 27 },
      { hour: "05", total: 1 },
    ]);
    expect(rollUpHourlyActuals([])).toEqual([]);
  });

  it("エリアの byHour ループと同じ（時ごとの最大・0 は捨てる・夜順）", () => {
    const rows = [
      { hour: 21, total: 10 },
      { hour: 21, total: 30 },
      { hour: 19, total: 5 },
      { hour: 2, total: 12 },
      { hour: 3, total: 0 },
      { hour: null, total: 99 },
    ];
    const legacy = legacyAreaBuckets(rows);
    const next = rollUpByNightHour(
      rows.filter((r): r is { hour: number; total: number } => r.hour !== null),
    );
    expect(next.map((b) => [b.hour, b.total])).toEqual(legacy);
    expect(next).toEqual([
      { hour: 19, total: 5 },
      { hour: 21, total: 30 },
      { hour: 2, total: 12 },
    ]);
  });
});
