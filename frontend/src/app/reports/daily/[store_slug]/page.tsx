import { cache } from "react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { getStoreMetaBySlugStrict, buildStoreFullName } from "@/app/config/stores";
import { FactsSummaryCard } from "@/components/blog/FactsSummaryCard";
import { ReservationLinkCard } from "@/components/ReservationLinkCard";
import { ReportViewTracker } from "@/components/ReportViewTracker";
import { readPublicFacts } from "@/lib/blog/publicFacts";
import { stripFrontmatter } from "@/lib/blog/mdx";
import {
  fetchLatestPublishedReportByStoreWithStatus,
  type PublishedReportRow,
} from "@/lib/supabase/blogDrafts";
import { decideReportAvailability, type ReportFetchResult } from "@/lib/reports/reportAvailability";
import { ReportTemporarilyUnavailable } from "@/components/reports/ReportTemporarilyUnavailable";
import { buildPageMetadata } from "@/lib/seo/pageMetadata";
import { formatJstTimestamp } from "@/lib/dateFormat";

/** 18:00/21:30 に更新されるので 60 秒ごとに再検証 */
export const revalidate = 60;

type Props = {
  params: Promise<{ store_slug: string }>;
};

/**
 * React cache() で同一リクエスト内の generateMetadata / page 呼び出しを重複排除する
 * （fetchLatestPublishedReportByStoreWithStatus は cache: "no-store" のため
 * fetch レベルの重複排除は効かない）。
 *
 * `WithStatus` 版を使うのは「0 件」と「取得できていない」を区別するため。
 * 区別せず一律 notFound() を返していた旧実装は、Supabase 障害中に実在するレポートの
 * URL を 404 にし、その 404 が CDN に焼き付いた（2026-09-09）。
 */
const resolveDailyReport = cache(
  async (storeSlug: string): Promise<ReportFetchResult<PublishedReportRow>> =>
    fetchLatestPublishedReportByStoreWithStatus(storeSlug, "daily"),
);

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { store_slug } = await params;
  const meta = getStoreMetaBySlugStrict(store_slug);
  if (!meta) notFound();

  // 404 にしてよいのは「取得できたうえで 0 件」のときだけ。取得失敗時は本文側と同じく
  // 「一時的に取得できません」を返すため、ここでも notFound() を呼ばない
  // （メタ自体は行の内容を使わないので、正常時の出力は変わらない）。
  const availability = decideReportAvailability(await resolveDailyReport(meta.slug));
  if (availability.state === "not-found") notFound();

  const label = buildStoreFullName(meta);
  const title = `${label} · Daily Report`;
  const description = `${label} の最新AI予測予報（18:00/21:30更新のうち最新）を表示します。`;
  return buildPageMetadata({
    title,
    description,
    path: `/reports/daily/${encodeURIComponent(store_slug)}`,
    ogType: "article",
    // Daily Report は毎日上書きされる速報（SNS/直リンク用）。同じ店の混雑は安定URLの
    // 店舗ページ /store/[slug] が主役なので、Daily は noindex にして検索での重複・
    // クロール浪費を避け、評価を店舗ページに集約する（follow は残しリンクは辿らせる）。
    // noindex なので canonical は出さない。
    canonical: false,
    robots: { index: false, follow: true },
  });
}

export default async function DailyReportStorePage({ params }: Props) {
  const { store_slug } = await params;
  const store = getStoreMetaBySlugStrict(store_slug);
  if (!store) notFound();

  const availability = decideReportAvailability(await resolveDailyReport(store.slug));
  if (availability.state === "not-found") notFound();
  if (availability.state === "temporarily-unavailable") {
    return (
      <ReportTemporarilyUnavailable
        storeLabel={store.label}
        storeSlug={store.slug}
        reportType="daily"
      />
    );
  }
  const row = availability.row;

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
        {/* 2026-08-26 計測レビューR2対応(§5-5): 内部リンクの ?store= を除去 */}
        <Link
          href={`/store/${store.slug}`}
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
          {row.target_date} / {formatJstTimestamp(row.updated_at ?? row.created_at)} 更新
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
          storeName={buildStoreFullName(store)}
          storeSlug={store.slug}
          brand={store.brand}
          utmCampaign="daily_report"
        />
      </div>
    </main>
  );
}
