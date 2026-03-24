import type { MetadataRoute } from "next";
import { getMetadataBaseUrl } from "@/lib/siteUrl";
import { getAllPostMetas } from "@/lib/blog/content";
import { STORES } from "./config/stores";

const AUTO_BLOG_SLOTS = ["evening_preview", "late_update"] as const;

export default function sitemap(): MetadataRoute.Sitemap {
  const base = getMetadataBaseUrl().toString().replace(/\/+$/, "");
  const now = new Date();

  const staticRoutes: MetadataRoute.Sitemap = [
    { url: `${base}/`, lastModified: now, changeFrequency: "hourly", priority: 1.0 },
    { url: `${base}/stores`, lastModified: now, changeFrequency: "daily", priority: 0.9 },
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

  // 定時自動更新の固定URL（上書き運用）をクロール対象に含める
  const autoBlogRoutes: MetadataRoute.Sitemap = STORES.flatMap((s) =>
    AUTO_BLOG_SLOTS.map((slot) => ({
      url: `${base}/blog/auto-${encodeURIComponent(s.slug)}-${slot}`,
      lastModified: now,
      changeFrequency: "daily" as const,
      priority: 0.75,
    })),
  );

  return [...staticRoutes, ...storeRoutes, ...blogRoutes, ...autoBlogRoutes];
}
