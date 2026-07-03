import { cache } from "react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { getPostBySlug } from "@/lib/blog/content";
import { getMetadataBaseUrl } from "@/lib/siteUrl";
import { fetchPublishedEditorialBySlug, type PublishedEditorialRow } from "@/lib/supabase/blogDrafts";
import { getStoreMetaBySlugStrict, buildStoreFullName } from "@/app/config/stores";

export const dynamicParams = true;

type Props = {
  params: Promise<{ slug: string }>;
};

type ResolvedPost =
  | { kind: "editorial"; row: PublishedEditorialRow }
  | { kind: "filesystem"; post: NonNullable<ReturnType<typeof getPostBySlug>> }
  | { kind: "none" };

function stripFrontmatter(raw: string): string {
  if (!raw.startsWith("---\n")) return raw;
  const end = raw.indexOf("\n---\n", 4);
  if (end < 0) return raw;
  return raw.slice(end + 5).trimStart();
}

/** mdx_content 先頭付近の見出し行（# / ## / ###）をタイトル候補として抽出する */
function extractFirstHeading(mdx: string): string | null {
  for (const line of mdx.split("\n")) {
    const m = line.match(/^#{1,3}\s+(.+)/);
    if (m) {
      const text = m[1].trim();
      if (text) return text;
    }
  }
  return null;
}

/** 見出し以外の最初の段落を description フォールバックとして抽出する（約120文字に切り詰め） */
function extractFirstParagraph(mdx: string): string | null {
  for (const rawLine of mdx.split("\n")) {
    const line = rawLine.trim();
    if (!line) continue;
    if (/^#{1,6}\s+/.test(line)) continue;
    if (/^[-*+]\s+/.test(line)) continue;
    if (/^\d+\.\s+/.test(line)) continue;
    if (line.startsWith(">")) continue;
    if (line.startsWith("```")) continue;
    const truncated = line.length > 120 ? `${line.slice(0, 120)}…` : line;
    return truncated;
  }
  return null;
}

/**
 * Supabase 編集記事 → ファイルシステム記事の順で解決する。
 * React cache() で同一リクエスト内の generateMetadata / page 呼び出しを重複排除する
 * （fetchPublishedEditorialBySlug は cache: "no-store" のため fetch レベルの重複排除は効かない）。
 */
const resolvePost = cache(async (slug: string): Promise<ResolvedPost> => {
  const row = await fetchPublishedEditorialBySlug(slug);
  if (row) return { kind: "editorial", row };

  const post = getPostBySlug(slug);
  if (post) return { kind: "filesystem", post };

  return { kind: "none" };
});

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const resolved = await resolvePost(slug);

  if (resolved.kind === "none") {
    // generateMetadata は streaming 前に実行されるため、ここで notFound() を呼ぶことで
    // 存在しない slug が soft-404（200 で notFound シェルを返す）になるのを防ぐ。
    notFound();
  }

  const base = getMetadataBaseUrl();
  const url = new URL(`/blog/${encodeURIComponent(slug)}`, base);

  if (resolved.kind === "editorial") {
    const { row } = resolved;
    const store = getStoreMetaBySlugStrict(row.store_slug);
    const storeName = store ? buildStoreFullName(store) : row.store_slug;
    const content = stripFrontmatter(row.mdx_content);
    const heading = extractFirstHeading(content);
    const paragraph = extractFirstParagraph(content);

    const title = heading || `${storeName} 分析レポート`;
    const description = paragraph || `${storeName} の編集記事（承認済み）です。`;

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

  // filesystem
  const { post } = resolved;
  const title = post.title;
  const description = post.description || `${post.title}について解説します。`;

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
  const resolved = await resolvePost(slug);
  if (resolved.kind === "none") notFound();

  if (resolved.kind === "editorial") {
    const { row } = resolved;
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

  // filesystem post
  const { post } = resolved;

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
        <h1 className="text-2xl font-bold leading-tight text-white md:text-3xl">{post.title}</h1>
        <p className="mt-2 text-sm text-white/60">{post.date}</p>
        {post.description && <p className="mt-4 text-base text-white/75">{post.description}</p>}
      </header>

      <article className="prose prose-invert mt-10 max-w-none prose-headings:text-white prose-p:text-white/80 prose-li:text-white/80">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{post.mdx}</ReactMarkdown>
      </article>
    </main>
  );
}
