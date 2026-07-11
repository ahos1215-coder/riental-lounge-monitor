import { describe, it, expect } from "vitest";
import { isUsableInitialSnapshot } from "./useStorePreviewData";

/**
 * rank9「夜境界直後にSSRシードが前夜回顧を出す（最大60-90s）」の回帰テスト。
 *
 * usableInitialSnapshot は従来 slug 一致だけを見ていたため、SSR で焼き込んだ時点と
 * クライアント mount 時点で夜境界（19:00 / 翌05:00 JST）を跨ぐと、前夜回顧の完了夜シード
 * （または逆に古い進行中シード）をそのまま表示し続けていた。slug に加えて completedNight の
 * 一致も要求し、食い違えばシードを破棄する（→ 即 run() で最新化）。
 */

const seed = (slug: string, completedNight: boolean) => ({ slug, completedNight });

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
