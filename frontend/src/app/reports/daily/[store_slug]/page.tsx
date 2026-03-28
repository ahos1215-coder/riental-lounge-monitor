import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { getStoreMetaBySlugStrict } from "@/app/config/stores";
import { FactsSummaryCard } from "@/components/blog/FactsSummaryCard";
import { ReservationLinkCard } from "@/components/ReservationLinkCard";
import { ReportViewTracker } from "@/components/ReportViewTracker";
import { readPublicFacts } from "@/lib/blog/publicFacts";
import { fetchLatestPublishedReportByStore } from "@/lib/supabase/blogDrafts";
import { getMetadataBaseUrl } from "@/lib/siteUrl";

type Props = {
  params: Promise<{ store_slug: string }>;
};

function stripFrontmatter(raw: string): string {
  if (!raw.startsWith("---\n")) return raw;
  const end = raw.indexOf("\n---\n", 4);
  if (end < 0) return raw;
  return raw.slice(end + 5).trimStart();
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { store_slug } = await params;
  const meta = getStoreMetaBySlugStrict(store_slug);
  const label = meta ? `オリエンタルラウンジ ${meta.label}` : store_slug;
  const title = `${label} · Daily Report`;
  const description = `${label} の最新AI予測予報（18:00/21:30更新のうち最新）を表示します。`;
  const base = getMetadataBaseUrl();
  return {
    title,
    description,
    openGraph: {
      title: `${title} | めぐりび`,
      description,
      url: new URL(`/reports/daily/${encodeURIComponent(store_slug)}`, base),
      type: "article",
      locale: "ja_JP",
    },
    twitter: {
      card: "summary_large_image",
      title: `${title} | めぐりび`,
      description,
    },
  };
}

export default async function DailyReportStorePage({ params }: Props) {
  const { store_slug } = await params;
  const store = getStoreMetaBySlugStrict(store_slug);
  if (!store) notFound();

  const row = await fetchLatestPublishedReportByStore(store.slug, "daily");
  if (!row) notFound();

  const content = stripFrontmatter(row.mdx_content);
  const publicFacts = row.facts_id ? readPublicFacts(row.facts_id) : null;
  const factsForThisStore = publicFacts?.store?.id ? publicFacts.store.id === store.slug : true;
  const facts = factsForThisStore ? publicFacts : null;

  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-10">
      <ReportViewTracker storeSlug={store.slug} reportType="daily" />
      <div className="mb-6 flex flex-wrap gap-4">
        <Link
          href="/reports"
          className="inline-flex items-center gap-2 text-sm text-white/70 transition hover:text-white"
        >
          <span aria-hidden>←</span>
          AI予測レポート一覧
        </Link>
        <Link
          href={`/store/${store.slug}?store=${store.slug}`}
          className="text-sm text-white/50 transition hover:text-white"
        >
          店舗ページ →
        </Link>
      </div>

      <header className="mb-8">
        <h1 className="text-2xl font-bold leading-tight text-white md:text-3xl">
          {store.label} Daily Report
        </h1>
        <p className="mt-2 text-sm text-white/60">
          {row.target_date} / 最新更新: {row.created_at ?? "-"}
        </p>
        <p className="mt-4 text-base text-white/75">
          18:00/21:30 の自動生成結果のうち、最新1件を表示しています。
        </p>
      </header>

      {facts && (
        <div className="mb-8">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-semibold text-white/90">参考データ（Facts）</h2>
            <p className="text-xs text-white/55">
              ※ レポート本文とは別生成の短い要約です。矛盾がある場合は本文を優先してください。
            </p>
          </div>
          <FactsSummaryCard facts={facts} />
        </div>
      )}

      <article className="prose prose-invert mt-10 max-w-none prose-headings:text-white prose-p:text-white/80 prose-li:text-white/80">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
      </article>

      <div className="mt-10">
        <ReservationLinkCard
          storeName={`オリエンタルラウンジ ${store.label}`}
          storeSlug={store.slug}
          utmCampaign="daily_report"
        />
      </div>
    </main>
  );
}
