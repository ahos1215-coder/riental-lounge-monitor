import type { MetadataRoute } from "next";
import { getMetadataBaseUrl } from "@/lib/siteUrl";
import { getAllPostMetas } from "@/lib/blog/content";
import { fetchAllPublishedEditorialSlugs } from "@/lib/supabase/blogDrafts";
import { STORES } from "./config/stores";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const base = getMetadataBaseUrl().toString().replace(/\/+$/, "");
  const now = new Date();

  const staticRoutes: MetadataRoute.Sitemap = [
    { url: `${base}/`, lastModified: now, changeFrequency: "hourly", priority: 1.0 },
    { url: `${base}/stores`, lastModified: now, changeFrequency: "daily", priority: 0.9 },
    { url: `${base}/reports`, lastModified: now, changeFrequency: "daily", priority: 0.9 },
    { url: `${base}/blog`, lastModified: now, changeFrequency: "daily", priority: 0.9 },
    // /mypage は robots.ts で Disallow しているため sitemap にも載せない（クロール指示の矛盾防止）。
  ];

  const storeRoutes: MetadataRoute.Sitemap = STORES.map((s) => ({
    url: `${base}/store/${encodeURIComponent(s.slug)}`,
    lastModified: now,
    changeFrequency: "hourly",
    priority: 0.9,
  }));

  // ファイルシステム記事（frontend/content/blog/*.mdx）
  const blogRoutes: MetadataRoute.Sitemap = getAllPostMetas().map((p) => ({
    url: `${base}/blog/${encodeURIComponent(p.slug)}`,
    lastModified: p.date ? new Date(p.date) : now,
    changeFrequency: "weekly",
    priority: 0.7,
  }));

  // Supabase 編集記事（LINE承認済み）。失敗時は空配列が返るため sitemap 全体は壊れない。
  const editorialSlugs = await fetchAllPublishedEditorialSlugs();
  const editorialRoutes: MetadataRoute.Sitemap = editorialSlugs.map((e) => ({
    url: `${base}/blog/${encodeURIComponent(e.public_slug)}`,
    lastModified: e.target_date ? new Date(e.target_date) : now,
    changeFrequency: "weekly",
    priority: 0.7,
  }));

  // Daily Report は noindex（速報・店舗ページに評価を集約）のため sitemap から除外。

  // Weekly Report: 毎週水曜更新の固定URL。
  // 相席屋(aisekiya)は weekly レポート生成ワークフロー未対応のため notFound() になる → sitemap から除外。
  // 現状 weekly が生成されるのは oriental の 38 店舗のみ。aisekiya 対応後は published 行 / weekly_enabled 判定に切り替える。
  const weeklyReportRoutes: MetadataRoute.Sitemap = STORES.filter((s) => s.brand === "oriental").map((s) => ({
    url: `${base}/reports/weekly/${encodeURIComponent(s.slug)}`,
    lastModified: now,
    changeFrequency: "weekly" as const,
    priority: 0.8,
  }));

  return [...staticRoutes, ...storeRoutes, ...blogRoutes, ...editorialRoutes, ...weeklyReportRoutes];
}
