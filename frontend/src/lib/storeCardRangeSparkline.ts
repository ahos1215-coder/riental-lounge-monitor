/**
 * 店舗カード用: /api/range（store + limit のみ）の JSON から実測スパークラインを組み立てる。
 * plan/DECISIONS: サーバ側の時間フィルタは入れない。ここでも生データを時系列で並べるだけ。
 */

export type StoreCardRangeRow = {
  ts?: string;
  men?: number | null;
  women?: number | null;
  total?: number | null;
};

/** 一覧・トップ・店舗詳細のカードで共通。API 負荷と描画のバランス */
export const STORE_CARD_RANGE_LIMIT = 48;
export const STORE_CARD_SPARKLINE_POINTS = 12;

function finiteNonNeg(v: unknown): number | null {
  if (typeof v === "number" && Number.isFinite(v)) {
    return Math.max(0, Math.round(v));
  }
  if (typeof v === "string" && v.trim() !== "") {
    const n = Number(v);
    if (Number.isFinite(n)) return Math.max(0, Math.round(n));
  }
  return null;
}

export function rangeRowTotal(p: StoreCardRangeRow): number | null {
  const t = finiteNonNeg(p.total);
  if (t !== null) return t;
  const m = finiteNonNeg(p.men);
  const w = finiteNonNeg(p.women);
  if (m === null && w === null) return null;
  return (m ?? 0) + (w ?? 0);
}

/** Flask `{ ok, rows }`・配列・`data` を吸収 */
export function parseRangeResponse(body: unknown): StoreCardRangeRow[] {
  if (Array.isArray(body)) return body as StoreCardRangeRow[];
  if (body && typeof body === "object") {
    const o = body as { data?: unknown; rows?: unknown };
    if (Array.isArray(o.rows)) return o.rows as StoreCardRangeRow[];
    if (Array.isArray(o.data)) return o.data as StoreCardRangeRow[];
  }
  return [];
}

export function orderedRangeRows(rows: StoreCardRangeRow[]): StoreCardRangeRow[] {
  const withTime = rows
    .map((r) => ({ r, t: typeof r.ts === "string" ? new Date(r.ts).getTime() : NaN }))
    .filter((x) => Number.isFinite(x.t));
  if (withTime.length > 0) {
    return withTime.sort((a, b) => a.t - b.t).map((x) => x.r);
  }
  return rows;
}

/** 行に total または男女のどちらかがあれば、その行の男女カウント（欠損は total から推定可能なら補う） */
function rowMenWomenForSparkline(r: StoreCardRangeRow): { m: number; w: number } | null {
  const total = rangeRowTotal(r);
  if (total === null) return null;

  let m = finiteNonNeg(r.men);
  let w = finiteNonNeg(r.women);

  if (m !== null && w !== null) {
    return { m, w };
  }
  if (m !== null && w === null) {
    return { m, w: Math.max(0, total - m) };
  }
  if (m === null && w !== null) {
    return { m: Math.max(0, total - w), w };
  }

  // total のみ等、男女いずれも実数として取れない行は推移に含めない
  return null;
}

/** 時刻順・実測合計の直近 N 点（予測は含めない） */
export function buildActualSparklineFromRange(
  rows: StoreCardRangeRow[],
  maxPoints: number,
): number[] {
  const ordered = orderedRangeRows(rows);
  const totals: number[] = [];
  for (const r of ordered) {
    const v = rangeRowTotal(r);
    if (v !== null) totals.push(v);
  }
  return totals.length ? totals.slice(-maxPoints) : [];
}

/** 実測の男女それぞれの直近 N 点（合計系列と同じ行集合・同じ並び） */
export function buildGenderSparklineFromRange(
  rows: StoreCardRangeRow[],
  maxPoints: number,
): { men: number[]; women: number[] } {
  const ordered = orderedRangeRows(rows);
  const men: number[] = [];
  const women: number[] = [];
  for (const r of ordered) {
    const pair = rowMenWomenForSparkline(r);
    if (pair === null) continue;
    men.push(pair.m);
    women.push(pair.w);
  }
  if (!men.length) return { men: [], women: [] };
  return {
    men: men.slice(-maxPoints),
    women: women.slice(-maxPoints),
  };
}

export function pickLatestRangeRow(rows: StoreCardRangeRow[]): StoreCardRangeRow | null {
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
