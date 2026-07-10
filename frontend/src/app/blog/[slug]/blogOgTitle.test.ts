import { describe, expect, it } from "vitest";

import { resolveBlogOgTitle } from "./opengraph-image";

const FALLBACK = "めぐりび｜相席ラウンジ攻略ブログ";

describe("resolveBlogOgTitle", () => {
  it("フロントマターの実タイトル（日本語）をそのまま使う", () => {
    expect(resolveBlogOgTitle("渋谷店：今夜の狙い目", "shibuya-tonight-20251220")).toBe(
      "渋谷店：今夜の狙い目",
    );
  });

  it("タイトル未取得でも slug 由来の英字は絶対に出さない（旧バグの再発防止）", () => {
    const out = resolveBlogOgTitle(null, "shibuya-tonight-20251220");
    expect(out).not.toMatch(/shibuya/i);
    expect(out).not.toMatch(/tonight/i);
    expect(out).toBe(FALLBACK);
  });

  it("getPostBySlug が title 欠落時に slug を返してきてもフォールバックする", () => {
    const slug = "some-untitled-post";
    expect(resolveBlogOgTitle(slug, slug)).toBe(FALLBACK);
  });

  it("空白のみ / undefined はフォールバックする", () => {
    expect(resolveBlogOgTitle("   ", "x")).toBe(FALLBACK);
    expect(resolveBlogOgTitle(undefined, "x")).toBe(FALLBACK);
  });

  it("長い日本語タイトルは maxLen で丸め末尾に … を付ける", () => {
    const long = "あ".repeat(60);
    const out = resolveBlogOgTitle(long, "x", 44);
    expect(out.length).toBe(44);
    expect(out.endsWith("…")).toBe(true);
  });

  it("前後の空白はトリムする", () => {
    expect(resolveBlogOgTitle("  タイトル  ", "x")).toBe("タイトル");
  });
});
