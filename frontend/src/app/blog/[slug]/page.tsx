import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { FactsSummaryCard } from "@/components/blog/FactsSummaryCard";
import { readPublicFacts } from "@/lib/blog/publicFacts";
import { getAllPostMetas, getPostBySlug } from "@/lib/blog/content";
import { getMetadataBaseUrl } from "@/lib/siteUrl";
import { fetchAutoBlogDraftByFactsId } from "@/lib/supabase/blogDrafts";
import { getStoreMetaBySlug } from "@/app/config/stores";

export const dynamicParams = true;

type SearchParams = Record<string, string | string[] | undefined>;

type Props = {
  params: Promise<{ slug: string }>;
  searchParams?: Promise<SearchParams>;
};

function normalizeParam(value: string | string[] | undefined): string | undefined {
  if (!value) return undefined;
  return Array.isArray(value) ? value[0] : value;
}

function pickFactsId(post: any): string | null {
  const v =
    post?.facts_id ??
    post?.factsId ??
    post?.facts_id_public ??
    post?.factsIdPublic ??
    post?.frontmatter?.facts_id ??
    post?.frontmatter?.factsId ??
    post?.frontmatter?.facts_id_public ??
    post?.frontmatter?.factsIdPublic ??
    post?.meta?.facts_id ??
    post?.meta?.factsId ??
    post?.meta?.facts_id_public ??
    post?.meta?.factsIdPublic;

  if (typeof v === "string" && v.trim().length) return v.trim();
  return null;
}

export function generateStaticParams() {
  const posts = getAllPostMetas();
  return posts.map((p: any) => ({ slug: p.slug }));
}

function parseAutoSlug(slug: string): { storeSlug: string; slot: string } | null {
  const m = /^auto-([a-z0-9_]+)-([a-z0-9_]+)$/i.exec(slug.trim());
  if (!m) return null;
  return { storeSlug: m[1], slot: m[2] };
}

function stripFrontmatter(raw: string): string {
  if (!raw.startsWith("---\n")) return raw;
  const end = raw.indexOf("\n---\n", 4);
  if (end < 0) return raw;
  return raw.slice(end + 5).trimStart();
}

export async function generateMetadata({
  params,
  searchParams,
}: {
  params: Promise<{ slug: string }>;
  searchParams?: Promise<SearchParams>;
}): Promise<Metadata> {
  const { slug } = await params;
  const sp = searchParams ? await searchParams : undefined;
  const preview = normalizeParam(sp?.preview);
  const isPreview = preview === process.env.BLOG_PREVIEW_TOKEN;

  const auto = parseAutoSlug(slug);
  if (auto) {
    const factsId = `auto_${auto.storeSlug}_${auto.slot}`;
    const row = await fetchAutoBlogDraftByFactsId(factsId);
    if (!row) return {};
    const meta = getStoreMetaBySlug(auto.storeSlug);
    const title = `【自動更新】${meta.label}の最新予測と混雑ヒント`;
    const description = `ML 2.0の最新推論から生成した自動更新記事です。`;
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

  const post = getPostBySlug(slug, { includeDraft: isPreview });
  if (!post) return {};
  if ((post as any).draft && !isPreview) return {};

  const title = String((post as any).title ?? (post as any).name ?? slug ?? "Blog");
  const description = (post as any).description ? String((post as any).description) : "";
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
      description: description || title,
    },
  };
}

export default async function BlogPostPage({ params, searchParams }: Props) {
  const { slug } = await params;
  const sp = searchParams ? await searchParams : undefined;
  const preview = normalizeParam(sp?.preview);
  const isPreview = Boolean(preview) && preview === process.env.BLOG_PREVIEW_TOKEN;

  const auto = parseAutoSlug(slug);
  if (auto) {
    const factsId = `auto_${auto.storeSlug}_${auto.slot}`;
    const row = await fetchAutoBlogDraftByFactsId(factsId);
    if (!row) notFound();
    const store = getStoreMetaBySlug(auto.storeSlug);
    const content = stripFrontmatter(row.mdx_content);
    const facts = readPublicFacts(row.facts_id);

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
            【自動更新】{store.label}の最新予測と混雑ヒント
          </h1>
          <p className="mt-2 text-sm text-white/60">
            {row.target_date} / {store.label}
          </p>
          <p className="mt-4 text-base text-white/75">
            18:00/21:30 の自動更新で最新化される固定URL記事です（SEO用上書き運用）。
          </p>
        </header>

        <FactsSummaryCard facts={facts} />

        <article className="prose prose-invert mt-10 max-w-none prose-headings:text-white prose-p:text-white/80 prose-li:text-white/80">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
        </article>
      </main>
    );
  }

  const post = getPostBySlug(slug, { includeDraft: true });
  if (!post) notFound();
  if ((post as any).draft && !isPreview) notFound();

  const factsId = pickFactsId(post);
  const facts = factsId ? readPublicFacts(factsId) : null;

  const title = String((post as any).title ?? slug);
  const date = String((post as any).date ?? "");
  const store = String((post as any).store ?? "");
  const description = (post as any).description ? String((post as any).description) : "";
  const content = typeof (post as any).mdx === "string" ? String((post as any).mdx) : "";

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
        <h1 className="text-2xl font-bold leading-tight text-white md:text-3xl">{title}</h1>
        <p className="mt-2 text-sm text-white/60">
          {date}
          {store ? ` / ${store}` : ""}
        </p>
        {description && <p className="mt-4 text-base text-white/75">{description}</p>}
      </header>

      <FactsSummaryCard facts={facts} />

      <article className="prose prose-invert mt-10 max-w-none prose-headings:text-white prose-p:text-white/80 prose-li:text-white/80">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
      </article>
    </main>
  );
}
