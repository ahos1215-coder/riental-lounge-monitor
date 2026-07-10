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

/**
 * ミニ推移グラフで「営業終了をまたぐ大きな時間ギャップ」を検出して折れ線を分割する閾値。
 * 5分間隔の通常サンプルは分割せず、閉店→翌開店の十数時間ギャップだけをセグメント境界にする。
 */
export const SPARKLINE_GAP_BREAK_MIN_MINUTES = 60;
export const SPARKLINE_GAP_BREAK_MEDIAN_MULT = 3;

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

function rowTs(r: StoreCardRangeRow): number {
  return typeof r.ts === "string" ? new Date(r.ts).getTime() : NaN;
}

/**
 * 時刻順・実測合計の直近 N 点（値＋各点の epoch ms タイムスタンプ）。
 * ミニチャートの「時間ギャップで折れ線を分割する」処理に times を使う。
 */
export function buildActualSparklineSeriesFromRange(
  rows: StoreCardRangeRow[],
  maxPoints: number,
): { values: number[]; times: number[] } {
  const ordered = orderedRangeRows(rows);
  const values: number[] = [];
  const times: number[] = [];
  for (const r of ordered) {
    const v = rangeRowTotal(r);
    if (v === null) continue;
    values.push(v);
    times.push(rowTs(r));
  }
  if (!values.length) return { values: [], times: [] };
  const start = Math.max(0, values.length - maxPoints);
  return { values: values.slice(start), times: times.slice(start) };
}

/** 時刻順・実測合計の直近 N 点（予測は含めない） */
export function buildActualSparklineFromRange(
  rows: StoreCardRangeRow[],
  maxPoints: number,
): number[] {
  return buildActualSparklineSeriesFromRange(rows, maxPoints).values;
}

/**
 * 実測の男女それぞれの直近 N 点＋各点のタイムスタンプ（合計系列と同じ行集合・同じ並び）。
 */
export function buildGenderSparklineSeriesFromRange(
  rows: StoreCardRangeRow[],
  maxPoints: number,
): { men: number[]; women: number[]; times: number[] } {
  const ordered = orderedRangeRows(rows);
  const men: number[] = [];
  const women: number[] = [];
  const times: number[] = [];
  for (const r of ordered) {
    const pair = rowMenWomenForSparkline(r);
    if (pair === null) continue;
    men.push(pair.m);
    women.push(pair.w);
    times.push(rowTs(r));
  }
  if (!men.length) return { men: [], women: [], times: [] };
  const start = Math.max(0, men.length - maxPoints);
  return {
    men: men.slice(start),
    women: women.slice(start),
    times: times.slice(start),
  };
}

/** 実測の男女それぞれの直近 N 点（合計系列と同じ行集合・同じ並び） */
export function buildGenderSparklineFromRange(
  rows: StoreCardRangeRow[],
  maxPoints: number,
): { men: number[]; women: number[] } {
  const s = buildGenderSparklineSeriesFromRange(rows, maxPoints);
  return { men: s.men, women: s.women };
}

function median(xs: number[]): number {
  if (!xs.length) return 0;
  const sorted = [...xs].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 !== 0
    ? sorted[mid]
    : (sorted[mid - 1] + sorted[mid]) / 2;
}

/**
 * 実測点のタイムスタンプ列 `times`（epoch ms・点と同順）を見て、営業終了をまたぐ大きな
 * 時間ギャップの手前で折れ線を分割するためのセグメント（点インデックスの配列）を返す。
 *
 * 分割条件: 直前点との差が「minGapMinutes 分」と「median ステップ × medianMult」の
 * 大きい方(= 閾値)を超えるとき。5分間隔の通常サンプルは分割されず、営業終了→翌開店の
 * 十数時間ギャップだけがセグメント境界になる。差が非有限(ts 欠損)の箇所では分割しない。
 *
 * 返り値は常に全インデックスを被覆する（times が空なら []、1点なら [[0]]）。
 */
export function segmentIndicesByTimeGaps(
  times: number[],
  opts?: { minGapMinutes?: number; medianMult?: number },
): number[][] {
  const n = times.length;
  if (n <= 1) return n === 1 ? [[0]] : [];

  const minGapMs =
    (opts?.minGapMinutes ?? SPARKLINE_GAP_BREAK_MIN_MINUTES) * 60_000;
  const medianMult = opts?.medianMult ?? SPARKLINE_GAP_BREAK_MEDIAN_MULT;

  const deltas: number[] = [];
  for (let i = 1; i < n; i++) {
    const d = times[i] - times[i - 1];
    if (Number.isFinite(d) && d > 0) deltas.push(d);
  }
  const threshold = Math.max(minGapMs, median(deltas) * medianMult);

  const segments: number[][] = [];
  let current: number[] = [0];
  for (let i = 1; i < n; i++) {
    const d = times[i] - times[i - 1];
    if (Number.isFinite(d) && d > threshold) {
      segments.push(current);
      current = [i];
    } else {
      current.push(i);
    }
  }
  segments.push(current);
  return segments;
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
