import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { getStoreMetaBySlugStrict } from "@/app/config/stores";
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

  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-10">
      <div className="mb-6">
        <Link
          href="/stores"
          className="inline-flex items-center gap-2 text-sm text-white/70 transition hover:text-white"
        >
          <span aria-hidden>←</span>
          店舗一覧へ戻る
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

      <article className="prose prose-invert mt-10 max-w-none prose-headings:text-white prose-p:text-white/80 prose-li:text-white/80">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
      </article>
    </main>
  );
}
