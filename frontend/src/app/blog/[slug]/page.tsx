import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { FactsSummaryCard } from "@/components/blog/FactsSummaryCard";
import { readPublicFacts } from "@/lib/blog/publicFacts";
import { getAllPostMetas, getPostBySlug } from "@/lib/blog/content";

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

  const post = getPostBySlug(slug, { includeDraft: isPreview });
  if (!post) return {};
  if ((post as any).draft && !isPreview) return {};

  const title = String((post as any).title ?? (post as any).name ?? slug ?? "Blog");
  const description = (post as any).description ? String((post as any).description) : "";
  return { title, description };
}

export default async function BlogPostPage({ params, searchParams }: Props) {
  const { slug } = await params;
  const sp = searchParams ? await searchParams : undefined;
  const preview = normalizeParam(sp?.preview);
  const isPreview = Boolean(preview) && preview === process.env.BLOG_PREVIEW_TOKEN;

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
        <Link href="/blog" className="inline-flex items-center gap-2 text-sm text-white/70 hover:text-white">
          驕ｶ鄙ｫ繝ｻ驛｢譎・§・取ｺｽ・ｹ・ｧ繝ｻ・ｰ髣包ｽｳ・つ鬮ｫ蛹・ｽｽ・ｧ驍ｵ・ｺ繝ｻ・ｸ髫ｰ魃会ｽｽ・ｻ驛｢・ｧ郢晢ｽｻ        </Link>
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
