import fs from "node:fs";
import path from "node:path";
import type { MetadataRoute } from "next";
import { getMetadataBaseUrl } from "@/lib/siteUrl";
import { getAllPostMetas } from "@/lib/blog/content";
import { fetchAllPublishedEditorialSlugs } from "@/lib/supabase/blogDrafts";
import { STORES } from "./config/stores";

/**
 * frontend/content/insights/weekly/{slug}/{YYYY-MM-DD}.json のうち最新のファイル名を
 * lastModified に使う（ファイル一覧の読み取りのみで中身はパースしないため安価）。
 * ディレクトリ/該当ファイルが無い店舗は null を返し、呼び出し側で now にフォールバックする。
 */
function latestWeeklyInsightDate(slug: string): Date | null {
  try {
    const dir = path.join(process.cwd(), "content", "insights", "weekly", slug);
    if (!fs.existsSync(dir)) return null;
    const files = fs.readdirSync(dir).filter((f) => /^\d{4}-\d{2}-\d{2}\.json$/.test(f));
    if (files.length === 0) return null;
    files.sort();
    const latest = files[files.length - 1]!.replace(/\.json$/, "");
    const d = new Date(`${latest}T00:00:00Z`);
    return Number.isNaN(d.getTime()) ? null : d;
  } catch {
    return null;
  }
}

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const base = getMetadataBaseUrl().toString().replace(/\/+$/, "");
  const now = new Date();

  const staticRoutes: MetadataRoute.Sitemap = [
    { url: `${base}/`, lastModified: now, changeFrequency: "hourly", priority: 1.0 },
    { url: `${base}/stores`, lastModified: now, changeFrequency: "daily", priority: 0.9 },
    { url: `${base}/reports`, lastModified: now, changeFrequency: "daily", priority: 0.9 },
    { url: `${base}/blog`, lastModified: now, changeFrequency: "daily", priority: 0.9 },
    // /compare は実ユーザー向けの店舗比較ページ（検索価値あり）。法務系ページ(/privacy /terms
    // /contact /disclaimer)は検索価値が低いため引き続き含めない。
    { url: `${base}/compare`, lastModified: now, changeFrequency: "daily", priority: 0.6 },
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

  // Daily Report は reports/daily/[store_slug]/page.tsx で明示的に
  // `robots: { index: false, follow: true }` を設定している（速報・店舗ページに評価を集約する
  // ための意図的な設計）。noindex ページを sitemap に載せると GSC の
  // 「noindex タグによって除外されました」エラーの原因になり矛盾指示になるため、
  // SEO Phase2 でも sitemap には追加しない（robots 側の方針を優先）。
  // Daily を indexable にする場合は、まず reports/daily の robots 指定を見直すのが先。

  // Weekly Report: 毎週水曜更新の固定URL。
  // 2026-07-03 時点でローカル gemma 生成が相席屋(aisekiya)にも対応し、全44店舗で published 行が存在するため
  // ブランドによる絞り込みは不要（以前は oriental のみ対応で aisekiya は notFound() になっていた）。
  // lastModified は content/insights/weekly/{slug} 配下の最新日付ファイルがあればそれを使い、
  // 無ければ now にフォールバックする（Supabase 側の実データを毎回叩くのは高コストなため）。
  const weeklyReportRoutes: MetadataRoute.Sitemap = STORES.map((s) => ({
    url: `${base}/reports/weekly/${encodeURIComponent(s.slug)}`,
    lastModified: latestWeeklyInsightDate(s.slug) ?? now,
    changeFrequency: "weekly" as const,
    priority: 0.8,
  }));

  return [...staticRoutes, ...storeRoutes, ...blogRoutes, ...editorialRoutes, ...weeklyReportRoutes];
}
