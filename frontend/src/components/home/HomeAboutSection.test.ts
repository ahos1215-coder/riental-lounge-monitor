import { describe, expect, it } from "vitest";

import { buildAboutCoverageLine } from "./HomeAboutSection";
import { STORES } from "@/app/config/stores";

/**
 * 所見3: 「まずはオリエンタルラウンジから対応」という旧文言は相席屋5店も対応済みの実態と
 * 食い違っていた。店舗数をハードコードせず STORES から動的に導出していることを検証する。
 */
describe("buildAboutCoverageLine", () => {
  it("STORES の実データから正しい店舗数を組み立てる（オリエンタル37・相席屋5・全42）", () => {
    const line = buildAboutCoverageLine(STORES);
    expect(line).toContain("オリエンタルラウンジ37店舗");
    expect(line).toContain("相席屋5店舗");
    expect(line).toContain("全42店舗");
  });

  it("ブランド構成が変わっても数値が追従する（ハードコードしていないことの回帰確認）", () => {
    const line = buildAboutCoverageLine([
      { brand: "oriental" },
      { brand: "oriental" },
      { brand: "aisekiya" },
    ]);
    expect(line).toContain("オリエンタルラウンジ2店舗");
    expect(line).toContain("相席屋1店舗");
    expect(line).toContain("全3店舗");
  });

  it("旧文言「まずはオリエンタルラウンジから対応し」は含まれない", () => {
    const line = buildAboutCoverageLine(STORES);
    expect(line).not.toContain("まずはオリエンタルラウンジから対応");
  });
});
