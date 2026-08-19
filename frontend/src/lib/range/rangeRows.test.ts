// frontend/src/lib/range/rangeRows.test.ts
//
// 番犬（C-05）: /api/range 行の「封筒ほどき・非負整数化・行合計・最新行」は 2026-08 まで
// 3+3+2+2 実装に分かれていた。lib/range/rangeRows.ts へ集約した後も、各モジュールの
// **旧実装と同じ値**を返すことを固定する（0 と null の取り違えは表示に直結する）。
import { describe, expect, it } from "vitest";
import {
  latestCountsOrZero,
  parseRangeEnvelope,
  pickLatestRow,
  rowTotalOrNull,
  toNonNegIntOrNull,
  type RangeRow,
} from "./rangeRows";
import { parseRangeResponse, rangeRowTotal, pickLatestRangeRow } from "@/lib/storeCardRangeSparkline";
import { parseRangePoints } from "@/app/hooks/storePreviewSnapshot";

// ---- 旧実装（写経。整えないこと） -----------------------------------------

/** 旧 storeCardRangeSparkline.parseRangeResponse / insightFromRange.pickArray（同一） */
function legacyParseArrayFirst(body: unknown): unknown[] {
  if (Array.isArray(body)) return body as unknown[];
  if (body && typeof body === "object") {
    const o = body as { data?: unknown; rows?: unknown };
    if (Array.isArray(o.rows)) return o.rows as unknown[];
    if (Array.isArray(o.data)) return o.data as unknown[];
  }
  return [];
}

/** 旧 storeCardRangeSparkline.finiteNonNeg / areaLiveSummary.toInt（同一） */
function legacyFiniteNonNeg(v: unknown): number | null {
  if (typeof v === "number" && Number.isFinite(v)) {
    return Math.max(0, Math.round(v));
  }
  if (typeof v === "string" && v.trim() !== "") {
    const n = Number(v);
    if (Number.isFinite(n)) return Math.max(0, Math.round(n));
  }
  return null;
}

/** 旧 ssrSummary.toNonNegativeInt（非数 → 0。入力は系列値＝number|null のみ） */
function legacyToNonNegativeInt(value: number | null | undefined): number {
  const n = Number(value ?? 0);
  if (!Number.isFinite(n)) return 0;
  return Math.max(0, Math.round(n));
}

/** 旧 storeCardRangeSparkline.rangeRowTotal（全欠損 → null） */
function legacyRangeRowTotal(p: RangeRow): number | null {
  const t = legacyFiniteNonNeg(p.total);
  if (t !== null) return t;
  const m = legacyFiniteNonNeg(p.men);
  const w = legacyFiniteNonNeg(p.women);
  if (m === null && w === null) return null;
  return (m ?? 0) + (w ?? 0);
}

/** 旧 areaLiveSummary.rowTotal（全欠損 → 0） */
function legacyAreaRowTotal(r: RangeRow): number {
  return legacyFiniteNonNeg(r.total) ?? (legacyFiniteNonNeg(r.men) ?? 0) + (legacyFiniteNonNeg(r.women) ?? 0);
}

/** 旧 storeCardRangeSparkline.pickLatestRangeRow */
function legacyPickLatestRangeRow(rows: RangeRow[]): RangeRow | null {
  if (!rows.length) return null;
  const scored = rows.map((r) => ({
    r,
    t: typeof r.ts === "string" ? new Date(r.ts).getTime() : NaN,
  }));
  const valid = scored.filter((x) => Number.isFinite(x.t));
  if (valid.length) {
    valid.sort((a, b) => b.t - a.t);
    return valid[0]!.r;
  }
  return rows[rows.length - 1] ?? null;
}

// ---- フィクスチャ ---------------------------------------------------------

const ROW_A = { ts: "2026-08-18T12:00:00Z", men: 10, women: 8, total: 18 };
const ROW_B = { ts: "2026-08-18T13:00:00Z", men: 12, women: 9 };
const ROW_NO_TS = { men: 3, women: 4, total: 7 };

const ENVELOPES: { name: string; body: unknown }[] = [
  { name: "配列直返し", body: [ROW_A, ROW_B] },
  { name: "{ok, rows}", body: { ok: true, rows: [ROW_A, ROW_B] } },
  { name: "{data}", body: { data: [ROW_A] } },
  { name: "rows と data の両方（rows 優先）", body: { rows: [ROW_A], data: [ROW_B] } },
  { name: "rows が配列でない", body: { rows: "nope", data: [ROW_B] } },
  { name: "空オブジェクト", body: {} },
  { name: "null", body: null },
  { name: "undefined", body: undefined },
  { name: "文字列", body: "oops" },
];

const SCALARS: unknown[] = [
  0,
  5,
  5.4,
  5.5,
  -3,
  "7",
  " 7 ",
  "",
  "  ",
  "abc",
  null,
  undefined,
  NaN,
  Infinity,
];

const ROWS: RangeRow[] = [
  { total: 20, men: 1, women: 2 },
  { men: 10, women: 8 },
  { men: 10 },
  { women: 8 },
  { total: 0 },
  { total: null, men: null, women: null },
  {},
  { total: "15" as unknown as number },
  { men: "3" as unknown as number, women: "4" as unknown as number },
];

describe("rangeRows — 旧実装との値等価（番犬）", () => {
  it("parseRangeEnvelope は旧 parseRangeResponse / pickArray と同じ", () => {
    for (const { name, body } of ENVELOPES) {
      expect(parseRangeEnvelope(body), name).toEqual(legacyParseArrayFirst(body));
      // 実際の呼び出し元（storeCardRangeSparkline）も同じ結果であること
      expect(parseRangeResponse(body), name).toEqual(legacyParseArrayFirst(body));
    }
  });

  it("toNonNegIntOrNull は旧 finiteNonNeg / toInt と同じ（非数は null）", () => {
    for (const v of SCALARS) {
      expect(toNonNegIntOrNull(v), String(v)).toBe(legacyFiniteNonNeg(v));
    }
  });

  it("`?? 0` を付けると旧 ssrSummary.toNonNegativeInt と同じ（系列値 number|null の範囲で）", () => {
    for (const v of [0, 5, 5.4, 5.5, -3, null, undefined] as (number | null | undefined)[]) {
      expect(toNonNegIntOrNull(v) ?? 0, String(v)).toBe(legacyToNonNegativeInt(v));
    }
  });

  it("rowTotalOrNull は旧 rangeRowTotal と同じ（全欠損は null）", () => {
    for (const r of ROWS) {
      expect(rowTotalOrNull(r), JSON.stringify(r)).toBe(legacyRangeRowTotal(r));
      expect(rangeRowTotal(r), JSON.stringify(r)).toBe(legacyRangeRowTotal(r));
    }
  });

  it("`?? 0` を付けると旧 areaLiveSummary.rowTotal と同じ（全欠損は 0）", () => {
    for (const r of ROWS) {
      expect(rowTotalOrNull(r) ?? 0, JSON.stringify(r)).toBe(legacyAreaRowTotal(r));
    }
    // 「全欠損＝0」と「全欠損＝null」の差がこの1件（エリアだけ 0 に倒している既存仕様）
    expect(rowTotalOrNull({})).toBeNull();
    expect(legacyAreaRowTotal({})).toBe(0);
  });

  it("pickLatestRow は旧 pickLatestRangeRow と同じ", () => {
    const cases: RangeRow[][] = [
      [],
      [ROW_A],
      [ROW_B, ROW_A],
      [ROW_NO_TS, ROW_A],
      [ROW_NO_TS, { men: 1 }],
      [{ ts: "not-a-date", men: 1 }, { ts: "not-a-date", men: 2 }],
    ];
    for (const rows of cases) {
      expect(pickLatestRow(rows)).toEqual(legacyPickLatestRangeRow(rows));
      expect(pickLatestRangeRow(rows)).toEqual(legacyPickLatestRangeRow(rows));
    }
  });

  it("parseRangePoints（店舗ページ）は ts を持つ行だけを通す", () => {
    expect(parseRangePoints({ rows: [ROW_A, ROW_NO_TS] })).toEqual([ROW_A]);
    expect(parseRangePoints({ data: [ROW_A] })).toEqual([ROW_A]);
    expect(parseRangePoints({})).toEqual([]);
    expect(parseRangePoints(null)).toEqual([]);
    // 【意図的な差分】旧 parseRangePoints は配列直返しを見ておらず常に [] を返していた。
    // /api/range は必ず {ok, rows} 封筒なので本番の応答形では差が出ない（空表示 → 表示可能になる方向）。
    expect(parseRangePoints([ROW_A, ROW_NO_TS])).toEqual([ROW_A]);
  });
});

// ---------------------------------------------------------------------------
// 番犬（Wave3）: 「最新行 → menNow / womenNow / nowTotal」の 3 行は app 層 4 箇所
// （mypage-client / store/[id]/StorePageClient / stores/page / stores-list-client）に
// バイト同一でコピーされていた。latestCountsOrZero へ寄せる前に、旧 3 行と 1 ビットも
// 違わないことを固定する。NaN も含めて同じであること（＝ toNonNegIntOrNull へは寄せない）。
// ---------------------------------------------------------------------------

/** 旧 app 層 4 箇所の 3 行（写経。整えないこと） */
function legacyLatestCounts(current: RangeRow): { men: number; women: number; total: number } {
  const menNow = Math.max(0, Math.round(Number(current.men ?? 0)));
  const womenNow = Math.max(0, Math.round(Number(current.women ?? 0)));
  const nowTotal = Math.max(0, Math.round(Number(current.total ?? menNow + womenNow)));
  return { men: menNow, women: womenNow, total: nowTotal };
}

describe("latestCountsOrZero は app 層 4 箇所の旧 3 行と同値", () => {
  const cases: RangeRow[] = [
    {},
    { men: 3, women: 4, total: 7 },
    // total が men+women と食い違う行（本番でも起こり得る）は total を優先＝旧実装と同じ
    { men: 3, women: 4, total: 99 },
    { men: 3, women: 4 },
    { men: 3 },
    { women: 4 },
    { total: 5 },
    { men: null, women: null, total: null },
    { men: -2, women: 4, total: -1 },
    { men: 2.4, women: 2.5, total: 4.9 },
    { men: "3" as unknown as number, women: "4" as unknown as number },
    { men: "x" as unknown as number },
    { ts: "2026-08-19T20:00:00Z", men: 1, women: 2, total: 3 },
  ];

  it("欠損・null・小数・負値・数値文字列で旧実装と一致する", () => {
    for (const row of cases) {
      expect(latestCountsOrZero(row), JSON.stringify(row)).toEqual(legacyLatestCounts(row));
    }
  });

  it("数値にならない値は旧実装どおり NaN のまま通す（0 に丸めない）", () => {
    const bad = { men: "x" as unknown as number };
    expect(Number.isNaN(latestCountsOrZero(bad).men)).toBe(true);
    expect(Number.isNaN(legacyLatestCounts(bad).men)).toBe(true);
  });

  it("null/undefined 行は 4 箇所の `pickLatestRangeRow(rows) ?? {}` と同じ扱い（全部 0）", () => {
    expect(latestCountsOrZero(null)).toEqual({ men: 0, women: 0, total: 0 });
    expect(latestCountsOrZero(undefined)).toEqual(legacyLatestCounts({}));
  });
});
