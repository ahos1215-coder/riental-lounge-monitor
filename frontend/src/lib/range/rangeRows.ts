// frontend/src/lib/range/rangeRows.ts
//
// /api/range の「行」を扱う小さな純粋関数の単一ソース。
//
// 経緯: 封筒（配列 / {rows} / {data}）のほどき方が 3 実装、非負整数化が 3 実装、
// 行合計が 2 実装、最新行の取り出しが 2 実装あり、「全欠損の行を 0 とみなすか null と
// みなすか」がモジュールごとに違っていた（エリア/店舗/カードで件数が食い違う原因）。
// ここでは **null 許容を既定**にし、0 が要る呼び出し側が `?? 0` を明示する。

/** /api/range の 1 行。欠損・null は本番でも普通に来る。 */
export type RangeRow = {
  ts?: string;
  men?: number | null;
  women?: number | null;
  total?: number | null;
};

/**
 * Flask の `{ ok, rows }`・`{ data }`・配列直返しのどれでも行配列を取り出す。
 * 行そのもののフィルタ（ts の有無など）はしない＝呼び出し側の責務。
 *
 * 型引数は「取り出した配列をどう見なすか」の宣言だけで、実行時の検証はしない
 * （旧 storeCardRangeSparkline.parseRangeResponse の `as` と同じ扱い）。
 * カード系は `parseRangeEnvelope<RangeRow>(body)` と書く。
 */
export function parseRangeEnvelope<T = unknown>(body: unknown): T[] {
  if (Array.isArray(body)) return body as T[];
  if (body && typeof body === "object") {
    const o = body as { rows?: unknown; data?: unknown };
    if (Array.isArray(o.rows)) return o.rows as T[];
    if (Array.isArray(o.data)) return o.data as T[];
  }
  return [];
}

/**
 * 非負整数化。数値または数値文字列だけを受け付け、それ以外（null/undefined/真偽値/
 * 空文字/数値でない文字列）は null を返す。0 が欲しい呼び出し側は `?? 0` を付ける。
 */
export function toNonNegIntOrNull(v: unknown): number | null {
  if (typeof v === "number" && Number.isFinite(v)) {
    return Math.max(0, Math.round(v));
  }
  if (typeof v === "string" && v.trim() !== "") {
    const n = Number(v);
    if (Number.isFinite(n)) return Math.max(0, Math.round(n));
  }
  return null;
}

/**
 * 行の合計人数。`total` があればそれを優先し、無ければ men+women を足す。
 * 3 つとも欠損している行は「値なし」＝ null（0 人と区別する）。
 */
export function rowTotalOrNull(r: RangeRow): number | null {
  const t = toNonNegIntOrNull(r.total);
  if (t !== null) return t;
  const m = toNonNegIntOrNull(r.men);
  const w = toNonNegIntOrNull(r.women);
  if (m === null && w === null) return null;
  return (m ?? 0) + (w ?? 0);
}

/**
 * カードの「いまの人数」3点セット（男 / 女 / 合計）。
 *
 * `toNonNegIntOrNull` とは**意図的に別物**なので混同しないこと:
 *   - こちらは欠損を 0 とみなす（`Number(x ?? 0)`）。カードは必ず数字を出すため。
 *   - 数値にならない値（真偽値・数値でない文字列）は `Number()` の結果をそのまま通す
 *     ＝ NaN になり得る。これは app 層 4 箇所（マイページ / 店舗詳細 / 一覧SSR /
 *     一覧クライアント）に同じ 3 行がコピーされていた既存挙動をそのまま関数にしたもの。
 *   - `total` が欠損している行だけ men+women で補う（`total` 優先は rowTotalOrNull と同じ）。
 */
export function latestCountsOrZero(r: RangeRow | null | undefined): {
  men: number;
  women: number;
  total: number;
} {
  const row = r ?? {};
  const men = Math.max(0, Math.round(Number(row.men ?? 0)));
  const women = Math.max(0, Math.round(Number(row.women ?? 0)));
  const total = Math.max(0, Math.round(Number(row.total ?? men + women)));
  return { men, women, total };
}

/**
 * 最新の行（ts が最も新しいもの）。ts が 1 つも解釈できない場合は配列の最後の行。
 * 空配列は null。
 */
export function pickLatestRow<T extends { ts?: string }>(rows: T[]): T | null {
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
