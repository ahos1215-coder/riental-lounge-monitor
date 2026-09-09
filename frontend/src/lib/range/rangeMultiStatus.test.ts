// 番犬テスト: 「取得失敗」を「0 人」に潰さないこと。
//
// 2026-09-09 の Supabase 402 事故では、/api/range_multi の by_slug が店舗ごとに
// { ok:false, error:"upstream-supabase", rows:[] } を返しているのに、読み手が rows しか
// 見ずに空配列 → 男0/女0/計0 として描画していた。全 42 店が「ガラガラ」に見える誤情報が
// 3 日半出続けた。ここでは「障害エントリからは人数を作れない」ことを型と値で固定する。
import { describe, expect, it } from "vitest";

import { readRangeMultiSlug, readSingleRangeOutcome } from "./rangeMultiStatus";
import { latestCountsOrZero, pickLatestRow } from "./rangeRows";

const OK_ENTRY = {
  rows: [
    { ts: "2026-09-09T21:00:00+09:00", men: 12, women: 9, total: 21 },
    { ts: "2026-09-09T21:05:00+09:00", men: 13, women: 10, total: 23 },
  ],
};

/** 実際に本番が返していた部分障害エントリ（oriental/routes/data_range.py の _fetch_slug）。 */
const OUTAGE_ENTRY = { ok: false, error: "upstream-supabase", rows: [] as unknown[] };

describe("readRangeMultiSlug", () => {
  it("成功エントリ（ok キー無し）は rows を返す", () => {
    const outcome = readRangeMultiSlug(OK_ENTRY);
    expect(outcome.available).toBe(true);
    if (!outcome.available) throw new Error("unreachable");
    expect(outcome.rows).toHaveLength(2);
    // 正常時の値は従来どおり（0 と混同しない側に倒しても数値は変わらない）
    const { men, women, total } = latestCountsOrZero(pickLatestRow(outcome.rows));
    expect({ men, women, total }).toEqual({ men: 13, women: 10, total: 23 });
  });

  it("ok:false のエントリは available:false（旧実装はここで 0 人を作っていた）", () => {
    const outcome = readRangeMultiSlug(OUTAGE_ENTRY);
    expect(outcome).toEqual({ available: false, reason: "upstream-error" });

    // 事故の再現: rows だけを見ると 0 人になってしまう、という対比を残す。
    const legacy = latestCountsOrZero(pickLatestRow(OUTAGE_ENTRY.rows as { ts?: string }[]));
    expect(legacy).toEqual({ men: 0, women: 0, total: 0 });
  });

  it("エントリが無い店は available:false（レスポンスから丸ごと欠けた場合）", () => {
    expect(readRangeMultiSlug(undefined)).toEqual({ available: false, reason: "missing" });
    expect(readRangeMultiSlug(null)).toEqual({ available: false, reason: "missing" });
    expect(readRangeMultiSlug({})).toEqual({ available: false, reason: "missing" });
  });

  it("成功でも観測行が 0 件なら available:false（未観測を 0 人と言わない）", () => {
    expect(readRangeMultiSlug({ rows: [] })).toEqual({ available: false, reason: "no-rows" });
  });

  it("行はあるが最新行の men/women/total が全部欠損なら available:false", () => {
    // 行数チェック（no-rows）だけではここをすり抜け、latestCountsOrZero が欠損を 0 に
    // 潰して「男性0 / 女性0 / 計0」を描いてしまう。欠測は 0 人ではない。
    const entry = {
      rows: [
        { ts: "2026-09-09T21:00:00+09:00", men: null, women: null, total: null },
        { ts: "2026-09-09T21:05:00+09:00" },
      ],
    };
    expect(readRangeMultiSlug(entry)).toEqual({ available: false, reason: "no-values" });

    // 事故の再現: 最新行だけ見ると 0 人になる、という対比を残す。
    expect(latestCountsOrZero(pickLatestRow(entry.rows))).toEqual({
      men: 0,
      women: 0,
      total: 0,
    });
  });

  it("本当に 0 人を観測した行は available:true のまま（欠測と 0 を混同しない）", () => {
    const outcome = readRangeMultiSlug({
      rows: [{ ts: "2026-09-09T21:05:00+09:00", men: 0, women: 0, total: 0 }],
    });
    expect(outcome.available).toBe(true);
  });

  it("最新行さえ埋まっていれば古い行が欠損でも available:true", () => {
    const outcome = readRangeMultiSlug({
      rows: [
        { ts: "2026-09-09T21:00:00+09:00", men: null, women: null, total: null },
        { ts: "2026-09-09T21:05:00+09:00", men: 13, women: 10, total: 23 },
      ],
    });
    expect(outcome.available).toBe(true);
    if (!outcome.available) throw new Error("unreachable");
    expect(outcome.rows).toHaveLength(2);
  });
});

describe("readSingleRangeOutcome（range_multi 失敗時の店舗別フォールバック）", () => {
  it("{ok:true, rows} は rows を返す", () => {
    const outcome = readSingleRangeOutcome({ ok: true, rows: OK_ENTRY.rows });
    expect(outcome.available).toBe(true);
  });

  it("{ok:false} は available:false", () => {
    expect(readSingleRangeOutcome({ ok: false, error: "upstream-supabase" })).toEqual({
      available: false,
      reason: "upstream-error",
    });
  });

  it("配列直返し・空配列・非オブジェクトも 0 人にしない", () => {
    expect(readSingleRangeOutcome(OK_ENTRY.rows).available).toBe(true);
    expect(readSingleRangeOutcome([])).toEqual({ available: false, reason: "no-rows" });
    expect(readSingleRangeOutcome({ ok: true, rows: [] })).toEqual({
      available: false,
      reason: "no-rows",
    });
    expect(readSingleRangeOutcome(null)).toEqual({ available: false, reason: "missing" });
  });

  it("行はあるが最新行が全部欠損なら available:false（配列直返しでも同じ）", () => {
    const emptyRow = [{ ts: "2026-09-09T21:05:00+09:00", men: null, women: null, total: null }];
    expect(readSingleRangeOutcome({ ok: true, rows: emptyRow })).toEqual({
      available: false,
      reason: "no-values",
    });
    expect(readSingleRangeOutcome(emptyRow)).toEqual({ available: false, reason: "no-values" });
  });
});
