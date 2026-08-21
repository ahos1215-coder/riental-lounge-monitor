// frontend/src/lib/compare/compareSeries.test.ts
//
// 番犬（2026-08-21 外部レビュー F7 / F10）:
//  F7 = 店舗ごとに秒がズレた実データ形の ts でも、各店の実測系列が「連続した配列」になること。
//  F10 = 夜窓（19:00-翌05:00 JST）の外（別の夜・日中）の行が混ざらないこと。
// どちらも描画そのものではなく、Recharts に渡す配列の中身を固定する。
import { describe, expect, it } from "vitest";
import { computeNightBaseDate, computeNightWindowFromBaseDate } from "@/lib/date/nightWindow";
import {
  COMPARE_SLOT_MS,
  buildActualSeries,
  buildCompareChartData,
  buildForecastSeries,
  compareHourlyTicks,
  floorToCompareSlot,
  hasNightRolledOver,
  nightWindowLabel,
  shouldApplyResponse,
} from "./compareSeries";
import type { RangeRow } from "@/lib/range/rangeRows";
import type { ForecastPoint } from "@/lib/forecast/types";

const identity = (n: number) => n;
const labelOf = (ts: number) => new Date(ts).toISOString().slice(11, 16);

// 2026-08-20(木) の夜窓 = 2026-08-20 19:00 JST 〜 2026-08-21 05:00 JST
const NIGHT = computeNightWindowFromBaseDate(new Date(2026, 7, 20));

describe("floorToCompareSlot", () => {
  it("5分スロットの開始時刻に切り下げる", () => {
    const base = Date.parse("2026-08-20T20:40:00+09:00");
    expect(floorToCompareSlot(Date.parse("2026-08-20T20:40:12.481+09:00"))).toBe(base);
    expect(floorToCompareSlot(Date.parse("2026-08-20T20:44:59.999+09:00"))).toBe(base);
    expect(floorToCompareSlot(base)).toBe(base);
    expect(floorToCompareSlot(base + COMPARE_SLOT_MS)).toBe(base + COMPARE_SLOT_MS);
  });

  it("非有限値は NaN（呼び出し側が捨てられるように）", () => {
    expect(Number.isNaN(floorToCompareSlot(Number.NaN))).toBe(true);
    expect(Number.isNaN(floorToCompareSlot(1, 0))).toBe(true);
  });
});

describe("F7: 店舗ごとに秒がバラバラでも実測系列が連続する", () => {
  // 本番の /api/range_multi が返す形（店舗ごとに収集時刻の秒がズレる）。
  const rowsA: RangeRow[] = [
    { ts: "2026-08-20T20:40:12.481+09:00", men: 10, women: 8, total: 18 },
    { ts: "2026-08-20T20:45:11.902+09:00", men: 11, women: 9, total: 20 },
    { ts: "2026-08-20T20:50:13.115+09:00", men: 12, women: 9, total: 21 },
  ];
  const rowsB: RangeRow[] = [
    { ts: "2026-08-20T20:40:37.004+09:00", men: 4, women: 5, total: 9 },
    { ts: "2026-08-20T20:45:36.771+09:00", men: 5, women: 5, total: 10 },
    { ts: "2026-08-20T20:50:38.220+09:00", men: 6, women: 6, total: 12 },
  ];

  const seriesBySlug = {
    a: { sparkline: buildActualSeries(rowsA, NIGHT, identity), forecast: [] },
    b: { sparkline: buildActualSeries(rowsB, NIGHT, identity), forecast: [] },
  };

  it("両店が同じ3行に乗る（歯抜けゼロ＝線が途切れない）", () => {
    const data = buildCompareChartData({ slugs: ["a", "b"], seriesBySlug, formatTime: labelOf });
    expect(data).toHaveLength(3);
    expect(data.map((r) => r.actual_a)).toEqual([18, 20, 21]);
    expect(data.map((r) => r.actual_b)).toEqual([9, 10, 12]);
    // 行の ts はスロット開始（秒が落ちている）
    expect(data.map((r) => r.ts)).toEqual([
      Date.parse("2026-08-20T20:40:00+09:00"),
      Date.parse("2026-08-20T20:45:00+09:00"),
      Date.parse("2026-08-20T20:50:00+09:00"),
    ]);
  });

  it("旧実装（ts 完全一致で和集合）なら歯抜けになることを対比で示す", () => {
    // 旧: 丸めずに ts をそのまま鍵にすると 6 行になり、各行に片方の店の値しか無い。
    const legacyTs = Array.from(
      new Set([...rowsA, ...rowsB].map((r) => new Date(r.ts as string).getTime())),
    ).sort((x, y) => x - y);
    expect(legacyTs).toHaveLength(6);
    const legacyRows = legacyTs.map((ts) => ({
      a: rowsA.find((r) => new Date(r.ts as string).getTime() === ts) ? 1 : 0,
      b: rowsB.find((r) => new Date(r.ts as string).getTime() === ts) ? 1 : 0,
    }));
    // どの行も「片方だけ」＝ null が1点おきに挟まる（connectNulls=false で線が消える）
    expect(legacyRows.every((r) => r.a + r.b === 1)).toBe(true);
  });

  it("予測（15分グリッド）は丸めても位置が変わらず、同じ行に実測と並ぶ", () => {
    const fc: ForecastPoint[] = [
      { ts: "2026-08-20T20:45:00+09:00", total_pred: 19 },
      { ts: "2026-08-20T21:00:00+09:00", total_pred: 24 },
      { ts: "2026-08-20T21:15:00+09:00", total_pred: null },
    ];
    const data = buildCompareChartData({
      slugs: ["a"],
      seriesBySlug: {
        a: {
          sparkline: buildActualSeries(rowsA, NIGHT, identity),
          forecast: buildForecastSeries(fc, NIGHT, identity),
        },
      },
      formatTime: labelOf,
    });
    const at2045 = data.find((r) => r.ts === Date.parse("2026-08-20T20:45:00+09:00"));
    expect(at2045?.actual_a).toBe(20);
    expect(at2045?.forecast_a).toBe(19);
    // total_pred=null の点は行そのものが生えない（0 埋めして平坦な線にしない）
    expect(data.find((r) => r.ts === Date.parse("2026-08-20T21:15:00+09:00"))).toBeUndefined();
  });
});

describe("F10: 夜窓の外（別の夜・日中）は混ざらない", () => {
  const rows: RangeRow[] = [
    { ts: "2026-08-19T21:40:00+09:00", total: 99 }, // 前の夜
    { ts: "2026-08-20T13:20:00+09:00", total: 1 }, // 日中
    { ts: "2026-08-20T18:59:00+09:00", total: 2 }, // 夜窓の直前
    { ts: "2026-08-20T19:00:00+09:00", total: 3 }, // 窓の始まり（含む）
    { ts: "2026-08-20T23:30:00+09:00", total: 30 },
    { ts: "2026-08-21T05:00:00+09:00", total: 5 }, // 窓の終わり（含む）
    { ts: "2026-08-21T05:05:00+09:00", total: 6 }, // 窓の外
    { ts: "2026-08-21T21:40:00+09:00", total: 77 }, // 次の夜
  ];

  it("19:00-翌05:00 の行だけを時刻順で拾う", () => {
    const series = buildActualSeries(rows, NIGHT, identity);
    expect(series.map((p) => p.total)).toEqual([3, 30, 5]);
  });

  it("予測も同じ夜窓で絞る（今夜の予測が昨夜の実測の右隣に生えない）", () => {
    const fc: ForecastPoint[] = [
      { ts: "2026-08-20T22:00:00+09:00", total_pred: 40 },
      { ts: "2026-08-21T22:00:00+09:00", total_pred: 41 },
    ];
    expect(buildForecastSeries(fc, NIGHT, identity).map((p) => p.total)).toEqual([40]);
  });

  it("表示値の変換（相席屋の%換算）は呼び出し側の関数を通す", () => {
    const series = buildActualSeries(rows, NIGHT, (n) => n * 2);
    expect(series.map((p) => p.total)).toEqual([6, 60, 10]);
  });
});

describe("nightWindowLabel", () => {
  it("どの夜のグラフかが分かる見出しを作る", () => {
    // 2026-08-20 は木曜
    expect(nightWindowLabel(new Date(2026, 7, 20))).toBe("8/20(木) 19:00 → 翌05:00");
  });
});

describe("compareHourlyTicks", () => {
  it("最初のちょうどの時から1時間刻み", () => {
    const from = Date.parse("2026-08-20T19:03:00+09:00");
    const to = Date.parse("2026-08-20T22:10:00+09:00");
    expect(compareHourlyTicks(from, to)).toEqual([
      Date.parse("2026-08-20T20:00:00+09:00"),
      Date.parse("2026-08-20T21:00:00+09:00"),
      Date.parse("2026-08-20T22:00:00+09:00"),
    ]);
  });

  it("データが無い/逆転しているときは空", () => {
    expect(compareHourlyTicks(Number.NaN, 1)).toEqual([]);
    expect(compareHourlyTicks(2, 1)).toEqual([]);
  });
});

describe("hasNightRolledOver", () => {
  const at = (iso: string) => new Date(iso);

  it("同じ夜のあいだは false", () => {
    // 20:00 JST に開き、23:00 JST になっても「同じ夜」
    const base = computeNightBaseDate(at("2026-08-20T11:00:00Z")); // 20:00 JST
    expect(hasNightRolledOver(base, at("2026-08-20T14:00:00Z"))).toBe(false); // 23:00 JST
  });

  it("深夜2時も前夜のまま（19時境界なので日付が変わっても同じ夜）", () => {
    const base = computeNightBaseDate(at("2026-08-20T11:00:00Z")); // 8/20 20:00 JST
    expect(hasNightRolledOver(base, at("2026-08-20T17:00:00Z"))).toBe(false); // 8/21 02:00 JST
  });

  it("18時台に開いたまま19時を過ぎたら true（今夜へ切り替える合図）", () => {
    const base = computeNightBaseDate(at("2026-08-20T09:30:00Z")); // 18:30 JST → 前夜(8/19)
    expect(hasNightRolledOver(base, at("2026-08-20T10:30:00Z"))).toBe(true); // 19:30 JST → 8/20
  });

  it("翌日の19時を過ぎても true", () => {
    const base = computeNightBaseDate(at("2026-08-20T11:00:00Z")); // 8/20の夜
    expect(hasNightRolledOver(base, at("2026-08-21T11:00:00Z"))).toBe(true); // 8/21の夜
  });
});

describe("shouldApplyResponse", () => {
  // 番犬（外部レビュー F10）: 比較ページのデータ取得 effect は AbortController も
  // cancelled フラグも世代チェックも無かったため、夜が19時をまたいで切り替わったとき
  // 「旧夜の fetch が新夜の fetch より後に解決する」と、見出しは新夜・グラフは旧夜という
  // 状態に無言で上書きされていた。effect 側は cancelled/世代(夜)の2つを渡すだけにして、
  // 「適用してよいか」の判定はこの純粋関数に切り出して固定する。
  it("cancelled でも夜が同じでも適用してよい（通常系）", () => {
    expect(
      shouldApplyResponse({ cancelled: false, requestNightYmd: "2026-08-20", currentNightYmd: "2026-08-20" }),
    ).toBe(true);
  });

  it("cleanup 済み（cancelled）なら夜が同じでも捨てる", () => {
    expect(
      shouldApplyResponse({ cancelled: true, requestNightYmd: "2026-08-20", currentNightYmd: "2026-08-20" }),
    ).toBe(false);
  });

  it("cancelled でなくても、応答が届く間に夜が変わっていたら捨てる（F10 の本丸）", () => {
    // 19:00 をまたいだ直後、旧夜(8/20)の fetch がまだ in-flight のまま
    // effect が再実行されて新夜(8/21)の nightYmd になった、というケース。
    expect(
      shouldApplyResponse({ cancelled: false, requestNightYmd: "2026-08-20", currentNightYmd: "2026-08-21" }),
    ).toBe(false);
  });

  it("cancelled かつ夜も違う（両方の理由が重なっても false のまま）", () => {
    expect(
      shouldApplyResponse({ cancelled: true, requestNightYmd: "2026-08-20", currentNightYmd: "2026-08-21" }),
    ).toBe(false);
  });
});
