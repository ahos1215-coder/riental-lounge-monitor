import { describe, expect, it, vi } from "vitest";

// 外部入力（ブログの fs・Supabase・傾向データ）を固定して、lastmod の決め方だけを検査する
vi.mock("@/lib/blog/content", () => ({
  getAllPostMetas: () => [
    { slug: "old-post", date: "2025-11-20" },
    { slug: "new-post", date: "2026-01-10" },
    { slug: "no-date-post", date: "" },
  ],
}));
vi.mock("@/lib/supabase/blogDrafts", () => ({
  fetchAllPublishedEditorialSlugs: async () => [],
}));
vi.mock("@/lib/store/storeTrendsData", () => ({
  getStoreTrendEntry: (slug: string) =>
    slug === "kokura"
      ? { weeks: ["2026-11-18", "2026-11-11"], periodStart: "2026-10-21", periodEnd: "2026-11-17", cells: [] }
      : slug === "hamamatsu"
        ? { weeks: ["2026-11-11"], periodStart: "2026-10-14", periodEnd: "2026-11-10", cells: [] }
        : null,
}));

import sitemap from "./sitemap";

async function byPath() {
  const entries = await sitemap();
  return new Map(entries.map((e) => [new URL(e.url).pathname, e]));
}

describe("sitemap の lastmod", () => {
  it("店舗ページは傾向データの最新週。データの無い店舗は lastmod を省く（生成時刻を入れない）", async () => {
    const m = await byPath();
    expect(m.get("/store/kokura")?.lastModified).toBe("2026-11-18");
    expect(m.get("/store/hamamatsu")?.lastModified).toBe("2026-11-11");
    expect(m.get("/store/shibuya")).toBeDefined();
    expect(m.get("/store/shibuya")?.lastModified).toBeUndefined();
  });

  it("エリアページは所属店舗の最新週。所属店舗にデータが無ければ省く", async () => {
    const m = await byPath();
    expect(m.get("/area/kokura")?.lastModified).toBe("2026-11-18");
    expect(m.get("/area/hamamatsu")?.lastModified).toBe("2026-11-11");
    expect(m.get("/area/osaka")?.lastModified).toBeUndefined();
  });

  it("トップ・一覧などは全店で最新の週、/blog は最新記事の日付", async () => {
    const m = await byPath();
    expect(m.get("/")?.lastModified).toBe("2026-11-18");
    expect(m.get("/stores")?.lastModified).toBe("2026-11-18");
    expect(new Date(m.get("/blog")!.lastModified as Date).toISOString().slice(0, 10)).toBe("2026-01-10");
    expect(m.get("/blog/no-date-post")?.lastModified).toBeUndefined();
  });

  it("どの URL にも「今この瞬間」の時刻が入らない", async () => {
    const before = Date.now() - 60_000;
    const entries = await sitemap();
    for (const e of entries) {
      if (!e.lastModified) continue;
      expect(new Date(e.lastModified).getTime()).toBeLessThan(before);
    }
  });
});
