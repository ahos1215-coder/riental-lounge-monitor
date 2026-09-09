// frontend/src/lib/range/rangeMultiStatus.ts
//
// 「0 人」と「取得できていない」を型で分ける単一ソース。
//
// なぜ必要か（2026-09-09・Supabase 402 事故）:
//   /api/range_multi は 1 店舗ぶんの取得に失敗しても全体は 200 を返し、その店の
//   by_slug エントリだけを `{ ok:false, error:"upstream-supabase", rows:[] }` にする
//   （oriental/routes/data_range.py の api_range_multi._fetch_slug）。ところが読み手は
//   `by_slug[slug]?.rows ?? []` としか見ておらず、空配列 → latestCountsOrZero() を通って
//   「男性0 / 女性0 / 計0」として描画していた。Supabase が全リクエストに 402 を返した
//   3 日半のあいだ、全 42 店が「ガラガラ」に見える**誤情報**が出続けたのはこれが原因。
//
//   障害を「0 人」と偽らないため、封筒のほどき方をここに一本化し、呼び出し側が
//   `available` を見ないと行を取り出せない形にする（0 と欠測を型で強制的に区別する）。
//
// 成功エントリに `ok` キーは無い（バックエンドは成功時 `{"rows": [...]}` だけを返す）。
// したがって判定は「`ok === false` なら失敗」であって「`ok !== true` なら失敗」ではない。

import { parseRangeEnvelope, pickLatestRow, rowTotalOrNull, type RangeRow } from "./rangeRows";

/** /api/range_multi の by_slug の 1 エントリ（成功時は rows のみ、失敗時は ok:false+error）。 */
export type RangeMultiSlugEntry = {
  ok?: boolean;
  error?: string;
  rows?: unknown[];
};

export type RangeUnavailableReason =
  /** その店の取得が上流（Supabase）で失敗した＝ by_slug エントリが ok:false。 */
  | "upstream-error"
  /** レスポンスにその店のエントリが無い（形が違う・店舗が丸ごと欠けた）。 */
  | "missing"
  /**
   * 取得自体は成功したが観測行が 1 行も無い。
   * 「0 人を観測した」ではなく「観測が存在しない」なので、人数は出さない側に倒す。
   */
  | "no-rows"
  /**
   * 行はあるが、最新行の men / women / total がどれも欠損している（値が入っていない）。
   * 描画に使う `latestCountsOrZero` は欠損を 0 に潰す仕様なので、ここで止めないと
   * 行数チェック（no-rows）をすり抜けて「男性0 / 女性0 / 計0」がそのまま出る。
   */
  | "no-values";

export type SlugRangeOutcome =
  | { available: true; rows: RangeRow[] }
  | { available: false; reason: RangeUnavailableReason };

/**
 * 取り出した行配列を「使える / 使えない」に判定する共通部分。
 *
 * 行数だけでなく**最新行に人数が入っているか**まで見るのが要点。カードが描く数字は
 * `latestCountsOrZero(pickLatestRow(rows))` で作られ、この関数は欠損を 0 に潰す
 * （rangeRows.ts のコメント参照）。したがって「行はあるが最新行の men/women/total が
 * 全部 null」という形は、行数チェックだけでは素通りして 0 人として描かれてしまう。
 * 0 人と欠測を分けるという目的からすると、ここも取得できていない側に倒すのが正しい。
 */
function outcomeFromRows(rows: RangeRow[]): SlugRangeOutcome {
  if (rows.length === 0) return { available: false, reason: "no-rows" };
  const latest = pickLatestRow(rows);
  // rowTotalOrNull は total 優先・3 つとも欠損なら null（＝「値なし」）を返す。
  if (latest === null || rowTotalOrNull(latest) === null) {
    return { available: false, reason: "no-values" };
  }
  return { available: true, rows };
}

/** /api/range_multi の by_slug エントリ 1 件を「取れた / 取れていない」に読み分ける。 */
export function readRangeMultiSlug(entry: unknown): SlugRangeOutcome {
  if (!entry || typeof entry !== "object" || Array.isArray(entry)) {
    return { available: false, reason: "missing" };
  }
  const e = entry as RangeMultiSlugEntry;
  if (e.ok === false) return { available: false, reason: "upstream-error" };
  if (!Array.isArray(e.rows)) return { available: false, reason: "missing" };
  return outcomeFromRows(parseRangeEnvelope<RangeRow>({ rows: e.rows }));
}

/**
 * 単体 /api/range のボディ（`{ok:true, rows:[...]}` / `{ok:false, error}` / 配列直返し）を
 * 同じ型に読み分ける。range_multi が丸ごと失敗したときの店舗別フォールバック用。
 */
export function readSingleRangeOutcome(body: unknown): SlugRangeOutcome {
  if (Array.isArray(body)) {
    return outcomeFromRows(parseRangeEnvelope<RangeRow>(body));
  }
  if (!body || typeof body !== "object") return { available: false, reason: "missing" };
  if ((body as { ok?: boolean }).ok === false) {
    return { available: false, reason: "upstream-error" };
  }
  return outcomeFromRows(parseRangeEnvelope<RangeRow>(body));
}
