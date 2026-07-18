import { describe, it, expect } from "vitest";
import { isUsableInitialSnapshot } from "./useStorePreviewData";
import { REALTIME_STALE_THRESHOLD_MIN } from "./storePreviewSnapshot";

/**
 * rank9「夜境界直後にSSRシードが前夜回顧を出す（最大60-90s）」の回帰テスト。
 *
 * usableInitialSnapshot は従来 slug 一致だけを見ていたため、SSR で焼き込んだ時点と
 * クライアント mount 時点で夜境界（19:00 / 翌05:00 JST）を跨ぐと、前夜回顧の完了夜シード
 * （または逆に古い進行中シード）をそのまま表示し続けていた。slug に加えて completedNight の
 * 一致も要求し、食い違えばシードを破棄する（→ 即 run() で最新化）。
 */

// latestActualTs はデフォルト null（＝computeFreshness が "none" を返し鮮度チェックの対象外）
// にしておくことで、このファイル内の既存の slug/completedNight テストは鮮度判定と無関係のまま
// 従来どおり動く。鮮度そのものをテストする箇所だけ明示的に latestActualTs を渡す。
const seed = (slug: string, completedNight: boolean, latestActualTs: string | null = null) => ({
  slug,
  completedNight,
  latestActualTs,
});

describe("isUsableInitialSnapshot — night-boundary seed guard", () => {
  it("accepts a seed when both slug and completedNight match the client", () => {
    expect(isUsableInitialSnapshot(seed("shibuya", false), "shibuya", false)).toBe(true);
    expect(isUsableInitialSnapshot(seed("shibuya", true), "shibuya", true)).toBe(true);
  });

  it("discards a seed baked for a different store", () => {
    expect(isUsableInitialSnapshot(seed("ueno", false), "shibuya", false)).toBe(false);
  });

  it("discards a 進行中 seed once the client has crossed the 05:00 boundary into a completed night", () => {
    // 焼き込み時 completedNight=false、mount 時 true → 前夜回顧化を防ぐため破棄。
    expect(isUsableInitialSnapshot(seed("shibuya", false), "shibuya", true)).toBe(false);
  });

  it("discards a 完了夜 seed once the client has crossed the 19:00 boundary into a new in-progress night", () => {
    // 焼き込み時 completedNight=true、mount 時 false → 古い回顧を出さないため破棄。
    expect(isUsableInitialSnapshot(seed("shibuya", true), "shibuya", false)).toBe(false);
  });

  it("discards a null/undefined seed", () => {
    expect(isUsableInitialSnapshot(null, "shibuya", false)).toBe(false);
    expect(isUsableInitialSnapshot(undefined, "shibuya", false)).toBe(false);
  });
});

/**
 * BUG #9「営業中なのに『閉店中・最終22:05時点』を初訪問者に最大90秒表示」の回帰テスト。
 *
 * 滅多に訪問されない店舗ページは ISR の stale-while-revalidate により古い HTML
 * （例: 22:05時点の実測が最新のまま）がそのまま返ることがある。slug/completedNight は
 * 一致していても、mount 時点で seed の latestActualTs が既に stale
 * （REALTIME_STALE_THRESHOLD_MIN=20分以上前）なら、ライブ表示（completedNight=false）に
 * 限ってシードを破棄し baseSnapshot + 即 run() に倒す（60-90s の遅延をスキップして
 * 即座に最新化する）。完了済みの夜（回顧的表示）は古い実測が仕様どおり正しいので対象外。
 * 実例: /store/nagoya_nishiki が 23:22 JST 時点で「閉店中・最終22:05時点」を表示していたが、
 * 実際の /api/range には 23:20 JST・180人の行が既に存在していた。
 */
describe("isUsableInitialSnapshot — BUG #9 live seed freshness guard", () => {
  const NOW = new Date("2026-07-18T14:22:00Z"); // 23:22 JST
  const STALE_TS = "2026-07-18T13:05:00Z"; // 22:05 JST（不具合報告の実例と同じ時刻、77分前）
  const minutesAgo = (min: number) => new Date(NOW.getTime() - min * 60_000).toISOString();

  it("accepts a FRESH live seed (today進行中・しきい値未満) → そのまま採用", () => {
    const s = seed("nagoya_nishiki", false, minutesAgo(5));
    expect(isUsableInitialSnapshot(s, "nagoya_nishiki", false, NOW)).toBe(true);
  });

  it("rejects a STALE live seed → BUG #9本体の再現(22:05時点のseedを23:22にmount)", () => {
    const s = seed("nagoya_nishiki", false, STALE_TS);
    expect(isUsableInitialSnapshot(s, "nagoya_nishiki", false, NOW)).toBe(false);
  });

  it("rejects exactly at REALTIME_STALE_THRESHOLD_MIN (computeFreshnessと同じ >= 境界)", () => {
    const s = seed("nagoya_nishiki", false, minutesAgo(REALTIME_STALE_THRESHOLD_MIN));
    expect(isUsableInitialSnapshot(s, "nagoya_nishiki", false, NOW)).toBe(false);
  });

  it("accepts just under the threshold (しきい値-1分は fresh 側)", () => {
    const s = seed("nagoya_nishiki", false, minutesAgo(REALTIME_STALE_THRESHOLD_MIN - 1));
    expect(isUsableInitialSnapshot(s, "nagoya_nishiki", false, NOW)).toBe(true);
  });

  it("still accepts an OLD seed for a completed-night view — 回顧的表示では古いデータが正しい仕様", () => {
    // 完了済みの夜（昨日/先週/過去日、または今日でも05:00-19:00の間）は、その夜の実測を
    // 回顧的に見せるビューなので、latestActualTs が何時間前でも stale 扱いにしない
    // （ライブ表示だけの制約であることの確認）。
    const s = seed("nagoya_nishiki", true, minutesAgo(600)); // 10時間前
    expect(isUsableInitialSnapshot(s, "nagoya_nishiki", true, NOW)).toBe(true);
  });

  it("does not reject solely for a null latestActualTs — データなしはstaleではない", () => {
    const s = seed("nagoya_nishiki", false, null);
    expect(isUsableInitialSnapshot(s, "nagoya_nishiki", false, NOW)).toBe(true);
  });

  it("a fresh timestamp never overrides an existing slug mismatch rejection", () => {
    const s = seed("ueno", false, minutesAgo(1));
    expect(isUsableInitialSnapshot(s, "nagoya_nishiki", false, NOW)).toBe(false);
  });
});
