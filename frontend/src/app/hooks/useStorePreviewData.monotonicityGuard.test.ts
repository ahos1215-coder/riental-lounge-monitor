import { describe, it, expect } from "vitest";
import { isStaleRefetch } from "./useStorePreviewData";

/**
 * rank4「鮮度が『1分前』→70秒後『13分前』へ逆行する」の回帰テスト。
 *
 * 60-90s の遅延バックグラウンド再取得や 15 分ポーリングは CDN→Next→backend の
 * キャッシュ層を経由するため、既に表示中のスナップショットより古い実測
 * （X-Vercel-Cache STALE で最大 13 分ほど古いデータ）を返すことがある。
 * isStaleRefetch はこの「古いデータでの上書き」を検出する純粋関数。
 */
describe("isStaleRefetch — rank4 freshness-regression guard", () => {
  it("rejects (true) when the refetched data is OLDER than what's currently displayed", () => {
    // 表示中: 1分前のデータ。再取得: 13分前のデータ（CDN STALE age=241s〜相当）。
    const current = new Date("2026-07-18T12:00:00Z").toISOString(); // "1分前"側の基準点
    const candidate = new Date("2026-07-18T11:48:00Z").toISOString(); // 12分古い
    expect(isStaleRefetch(candidate, current)).toBe(true);
  });

  it("accepts (false) when the refetched data is NEWER than what's currently displayed", () => {
    const current = new Date("2026-07-18T12:00:00Z").toISOString();
    const candidate = new Date("2026-07-18T12:05:00Z").toISOString(); // 5分進んでいる
    expect(isStaleRefetch(candidate, current)).toBe(false);
  });

  it("accepts (false) when the timestamps are exactly equal (no regression, no-op overwrite is fine)", () => {
    const ts = new Date("2026-07-18T12:00:00Z").toISOString();
    expect(isStaleRefetch(ts, ts)).toBe(false);
  });

  it("accepts (false) when there is nothing currently displayed yet (current is null) — first load / post mode-switch reset", () => {
    const candidate = new Date("2026-07-18T11:48:00Z").toISOString();
    expect(isStaleRefetch(candidate, null)).toBe(false);
    expect(isStaleRefetch(candidate, undefined)).toBe(false);
  });

  it("accepts (false) when the candidate has no actual data at all (candidate is null)", () => {
    const current = new Date("2026-07-18T12:00:00Z").toISOString();
    expect(isStaleRefetch(null, current)).toBe(false);
    expect(isStaleRefetch(undefined, current)).toBe(false);
  });

  it("accepts (false) for invalid/unparseable timestamps (fails safe = allow the update through)", () => {
    const current = new Date("2026-07-18T12:00:00Z").toISOString();
    expect(isStaleRefetch("not-a-date", current)).toBe(false);
    expect(isStaleRefetch(current, "not-a-date")).toBe(false);
  });
});
