import type { MetadataRoute } from "next";
import { getMetadataBaseUrl } from "@/lib/siteUrl";
import { getAllPostMetas } from "@/lib/blog/content";
import { STORES } from "./config/stores";

export default function sitemap(): MetadataRoute.Sitemap {
  const base = getMetadataBaseUrl().toString().replace(/\/+$/, "");
  const now = new Date();

  const staticRoutes: MetadataRoute.Sitemap = [
    { url: `${base}/`, lastModified: now, changeFrequency: "hourly", priority: 1.0 },
    { url: `${base}/stores`, lastModified: now, changeFrequency: "daily", priority: 0.9 },
    { url: `${base}/reports`, lastModified: now, changeFrequency: "daily", priority: 0.9 },
    { url: `${base}/blog`, lastModified: now, changeFrequency: "daily", priority: 0.9 },
    { url: `${base}/mypage`, lastModified: now, changeFrequency: "weekly", priority: 0.5 },
  ];

  const storeRoutes: MetadataRoute.Sitemap = STORES.map((s) => ({
    url: `${base}/store/${encodeURIComponent(s.slug)}`,
    lastModified: now,
    changeFrequency: "hourly",
    priority: 0.8,
  }));

  const blogRoutes: MetadataRoute.Sitemap = getAllPostMetas().map((p) => ({
    url: `${base}/blog/${encodeURIComponent(p.slug)}`,
    lastModified: p.date ? new Date(p.date) : now,
    changeFrequency: "weekly",
    priority: 0.7,
  }));

  // Daily Report: 定時自動更新の固定URL（毎日上書き）
  const dailyReportRoutes: MetadataRoute.Sitemap = STORES.map((s) => ({
    url: `${base}/reports/daily/${encodeURIComponent(s.slug)}`,
    lastModified: now,
    changeFrequency: "daily" as const,
    priority: 0.85,
  }));

  // Weekly Report: 毎週水曜更新の固定URL
  const weeklyReportRoutes: MetadataRoute.Sitemap = STORES.map((s) => ({
    url: `${base}/reports/weekly/${encodeURIComponent(s.slug)}`,
    lastModified: now,
    changeFrequency: "weekly" as const,
    priority: 0.8,
  }));

  return [...staticRoutes, ...storeRoutes, ...blogRoutes, ...dailyReportRoutes, ...weeklyReportRoutes];
}
