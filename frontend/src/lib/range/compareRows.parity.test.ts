// frontend/src/lib/range/compareRows.parity.test.ts
//
// 番犬（Wave3・取りこぼし監査）: /compare は /api/range_multi の行を独自に扱っていた
// 4 系統目だった（最新行＝配列末尾固定・合計＝men+women で total 列を無視）。
// lib/range（pickLatestRow / rowTotalOrNull）へ寄せる前に、
// **本番で来る形（rows は ts 昇順・total == men+women）では 1 ビットも変わらない**
// ことを固定する。差が出る条件（順不同・total だけある行）も「意図した改善」として明示する。
import { describe, expect, it } from "vitest";
import { pickLatestRow, rowTotalOrNull, type RangeRow } from "./rangeRows";

// ---- 旧実装（compare-client.tsx から写経。整えないこと） --------------------

/** 旧: 最新行 = 配列の末尾（ts を見ない） */
function legacyLatest(rows: RangeRow[]): RangeRow | undefined {
  return rows[rows.length - 1];
}

/** 旧: 行合計 = men + women（total 列は無視） */
function legacyRowTotal(r: RangeRow): number {
  return (r.men ?? 0) + (r.women ?? 0);
}

/** 旧: スパークライン（ts を持つ行だけ、合計は men+women） */
function legacySeries(rows: RangeRow[]): { ts: number; total: number }[] {
  return rows
    .filter((r): r is RangeRow & { ts: string } => Boolean(r.ts))
    .map((r) => ({ ts: new Date(r.ts).getTime(), total: legacyRowTotal(r) }));
}

// ---- 新実装（compare-client が使う組み合わせ） -----------------------------

function newLatest(rows: RangeRow[]): RangeRow | undefined {
  return pickLatestRow(rows) ?? undefined;
}

function newSeries(rows: RangeRow[]): { ts: number; total: number }[] {
  return rows
    .filter((r): r is RangeRow & { ts: string } => Boolean(r.ts))
    .map((r) => ({ ts: new Date(r.ts).getTime(), total: rowTotalOrNull(r) ?? 0 }));
}

// ---- フィクスチャ: 本番の /api/range_multi が返す形 ------------------------
// Flask は ts 昇順で返し、total は men+women と一致する（collect 時に同時に書く）。

const NORMAL_ROWS: RangeRow[] = [
  { ts: "2026-08-19T10:00:00Z", men: 4, women: 6, total: 10 },
  { ts: "2026-08-19T10:05:00Z", men: 5, women: 7, total: 12 },
  { ts: "2026-08-19T10:10:00Z", men: 9, women: 11, total: 20 },
  { ts: "2026-08-19T10:15:00Z", men: 0, women: 0, total: 0 },
  { ts: "2026-08-19T10:20:00Z", men: 12, women: 13, total: 25 },
];

const EMPTY_ROWS: RangeRow[] = [];

describe("compare の /api/range 行の扱い: 通常データでは旧実装と完全一致", () => {
  it("最新行（ts 昇順で返る本番データでは末尾＝ts 最大）", () => {
    expect(newLatest(NORMAL_ROWS)).toEqual(legacyLatest(NORMAL_ROWS));
    expect(newLatest(EMPTY_ROWS)).toEqual(legacyLatest(EMPTY_ROWS));
  });

  it("最新行の men / women（?? 0 の形は据え置き）", () => {
    const oldL = legacyLatest(NORMAL_ROWS);
    const newL = newLatest(NORMAL_ROWS);
    expect(newL?.men ?? 0).toBe(oldL?.men ?? 0);
    expect(newL?.women ?? 0).toBe(oldL?.women ?? 0);
  });

  it("最新行の合計（total == men+women の行では同値）", () => {
    const oldL = legacyLatest(NORMAL_ROWS) ?? {};
    const newL = newLatest(NORMAL_ROWS) ?? {};
    expect(rowTotalOrNull(newL) ?? 0).toBe(legacyRowTotal(oldL));
  });

  it("スパークライン系列（全点）", () => {
    expect(newSeries(NORMAL_ROWS)).toEqual(legacySeries(NORMAL_ROWS));
  });

  it("men/women のみ（total 欠損）の行でも同値", () => {
    const rows: RangeRow[] = [
      { ts: "2026-08-19T10:00:00Z", men: 4, women: 6 },
      { ts: "2026-08-19T10:05:00Z", men: 5, women: 7 },
    ];
    expect(newSeries(rows)).toEqual(legacySeries(rows));
    expect(rowTotalOrNull(newLatest(rows) ?? {}) ?? 0).toBe(legacyRowTotal(legacyLatest(rows) ?? {}));
  });
});

describe("差が出るのは異常データのときだけ（意図した改善。報告に明記）", () => {
  it("rows が時系列順でない場合: 旧＝末尾 / 新＝ts 最大", () => {
    const rows: RangeRow[] = [
      { ts: "2026-08-19T10:20:00Z", men: 12, women: 13, total: 25 },
      { ts: "2026-08-19T10:00:00Z", men: 4, women: 6, total: 10 },
    ];
    expect(legacyLatest(rows)?.total).toBe(10);
    expect(newLatest(rows)?.total).toBe(25);
  });

  it("total 列だけある行: 旧＝0人扱い / 新＝total を採用", () => {
    const row: RangeRow = { ts: "2026-08-19T10:00:00Z", total: 18 };
    expect(legacyRowTotal(row)).toBe(0);
    expect(rowTotalOrNull(row) ?? 0).toBe(18);
  });

  it("total と men+women が食い違う行: 旧＝men+women / 新＝total 優先（他ページと同じ）", () => {
    const row: RangeRow = { ts: "2026-08-19T10:00:00Z", men: 1, women: 1, total: 30 };
    expect(legacyRowTotal(row)).toBe(2);
    expect(rowTotalOrNull(row) ?? 0).toBe(30);
  });
});
