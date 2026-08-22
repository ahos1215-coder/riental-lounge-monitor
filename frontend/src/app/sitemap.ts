import type { MetadataRoute } from "next";
import { getMetadataBaseUrl } from "@/lib/siteUrl";
import { getAllPostMetas } from "@/lib/blog/content";
import { fetchAllPublishedEditorialSlugs } from "@/lib/supabase/blogDrafts";
import { STORES } from "./config/stores";
import { AREAS } from "./config/areas";

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

  // SEO Phase2続き〜seo/c-area-hub: エリア横断ハブページ。大阪・名古屋・渋谷・上野・横浜の
  // 複数店舗集約ハブ5件に加え、静岡・浜松・町田・小倉・神戸・熊本・大分・高崎の単独店舗ハブ8件を
  // 含む計14エリア（実体は AREAS 配列で自動反映、ここで件数をハードコードしない）。
  // ビッグキーワード（例:「大阪 相席ラウンジ」）向けの集約ページ。店舗ページよりわずかに低い優先度。
  const areaRoutes: MetadataRoute.Sitemap = AREAS.map((a) => ({
    url: `${base}/area/${encodeURIComponent(a.id)}`,
    lastModified: now,
    changeFrequency: "daily",
    priority: 0.85,
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

  // Weekly Report は reports/weekly/[store_slug]/page.tsx で Daily と同じく
  // `robots: { index: false, follow: true }` を設定している（速報・店舗ページに評価を集約する
  // ための意図的な設計。Daily 側の説明と同じ理由）。
  // 2026-08-20 の 17e815f で Weekly を noindex 化した際、この sitemap.ts を直し忘れて
  // 「noindex なのに sitemap に載っている」矛盾状態のまま2026-08-22の外部レビューまで
  // 気付かれずに残っていた（GSCの「noindexタグによって除外されました」エラーの原因）。
  // Daily と同じ扱いに揃え、sitemap には載せない。

  return [...staticRoutes, ...storeRoutes, ...areaRoutes, ...blogRoutes, ...editorialRoutes];
}
