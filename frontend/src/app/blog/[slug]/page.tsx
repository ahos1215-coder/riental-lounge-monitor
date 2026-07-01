import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { getMetadataBaseUrl } from "@/lib/siteUrl";
import { fetchPublishedEditorialBySlug } from "@/lib/supabase/blogDrafts";
import { getStoreMetaBySlugStrict, buildStoreFullName } from "@/app/config/stores";

export const dynamicParams = true;

type Props = {
  params: Promise<{ slug: string }>;
};

function stripFrontmatter(raw: string): string {
  if (!raw.startsWith("---\n")) return raw;
  const end = raw.indexOf("\n---\n", 4);
  if (end < 0) return raw;
  return raw.slice(end + 5).trimStart();
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const row = await fetchPublishedEditorialBySlug(slug);
  if (!row) return {};
  const store = getStoreMetaBySlugStrict(row.store_slug);
  const storeName = store ? buildStoreFullName(store) : row.store_slug;
  const title = `${storeName} 分析レポート`;
  const description = `${storeName} の編集記事（承認済み）です。`;
  const base = getMetadataBaseUrl();
  const url = new URL(`/blog/${encodeURIComponent(slug)}`, base);

  return {
    title,
    description,
    alternates: { canonical: url.href },
    openGraph: {
      title,
      description,
      url,
      type: "article",
      locale: "ja_JP",
    },
    twitter: {
      card: "summary_large_image",
      title,
      description,
    },
  };
}

export default async function BlogPostPage({ params }: Props) {
  const { slug } = await params;
  const row = await fetchPublishedEditorialBySlug(slug);
  if (!row) notFound();

  const store = getStoreMetaBySlugStrict(row.store_slug);
  const content = stripFrontmatter(row.mdx_content);

  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-10">
      <div className="mb-6">
        <Link
          href="/blog"
          className="inline-flex items-center gap-2 text-sm text-white/70 transition hover:text-white"
        >
          <span aria-hidden="true">←</span>
          ブログ一覧へ戻る
        </Link>
      </div>

      <header className="mb-8">
        <h1 className="text-2xl font-bold leading-tight text-white md:text-3xl">
          {store ? `${store.label} 分析レポート` : `${row.store_slug} 分析レポート`}
        </h1>
        <p className="mt-2 text-sm text-white/60">
          {row.target_date}
          {store ? ` / ${store.label}` : ""}
        </p>
        <p className="mt-4 text-base text-white/75">LINE承認済みの編集記事です。</p>
      </header>

      <article className="prose prose-invert mt-10 max-w-none prose-headings:text-white prose-p:text-white/80 prose-li:text-white/80">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
      </article>
    </main>
  );
}
