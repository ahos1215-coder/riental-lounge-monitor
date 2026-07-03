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
  // 2026-07-03 時点でローカル gemma 生成が相席屋(aisekiya)にも対応し、全44店舗で published 行が存在するため
  // ブランドによる絞り込みは不要（以前は oriental のみ対応で aisekiya は notFound() になっていた）。
  const weeklyReportRoutes: MetadataRoute.Sitemap = STORES.map((s) => ({
    url: `${base}/reports/weekly/${encodeURIComponent(s.slug)}`,
    lastModified: now,
    changeFrequency: "weekly" as const,
    priority: 0.8,
  }));

  return [...staticRoutes, ...storeRoutes, ...blogRoutes, ...editorialRoutes, ...weeklyReportRoutes];
}
