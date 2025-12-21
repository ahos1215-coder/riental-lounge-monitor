import fs from "node:fs";
import path from "node:path";
import matter from "gray-matter";

export type BlogCategoryId = "guide" | "beginner" | "prediction" | "column" | "interview";
export type BlogLevel = "easy" | "normal" | "pro";
export type BlogPeriod = "tonight" | "this_week" | "generic";

export type BlogPostMeta = {
  slug: string;
  title: string;
  description: string;
  date: string; // YYYY-MM-DD
  minutes: number;
  views: number;

  categoryId: BlogCategoryId;

  // 任意：MVPでは使わなくてもOK（後で効く）
  storeId?: string;
  level?: BlogLevel;
  period?: BlogPeriod;
  factsId?: string;

  // frontmatter: facts_visibility: "hide" のときだけ Facts 非表示
  factsVisibility?: "show" | "hide";

  draft?: boolean;
};

export type BlogPost = BlogPostMeta & {
  mdx: string; // 本文（MD/MDXファイルの frontmatter 除いた部分）
};

export const BLOG_CATEGORIES: Array<{
  id: "all" | BlogCategoryId;
  label: string;
  badgeClassName: string;
  heroClassName: string;
}> = [
  {
    id: "all",
    label: "すべて",
    badgeClassName: "bg-white/10",
    heroClassName: "bg-gradient-to-br from-indigo-500/20 via-fuchsia-500/10 to-amber-400/10",
  },
  {
    id: "guide",
    label: "使い方ガイド",
    badgeClassName: "bg-sky-500/90",
    heroClassName: "bg-gradient-to-br from-sky-500/25 via-indigo-500/10 to-emerald-400/10",
  },
  {
    id: "beginner",
    label: "初心者向け",
    badgeClassName: "bg-pink-500/90",
    heroClassName: "bg-gradient-to-br from-pink-500/25 via-fuchsia-500/10 to-amber-400/10",
  },
  {
    id: "prediction",
    label: "予測の仕組み",
    badgeClassName: "bg-emerald-500/90",
    heroClassName: "bg-gradient-to-br from-emerald-500/25 via-sky-500/10 to-indigo-500/10",
  },
  {
    id: "column",
    label: "コラム",
    badgeClassName: "bg-violet-500/90",
    heroClassName: "bg-gradient-to-br from-violet-500/25 via-indigo-500/10 to-amber-400/10",
  },
  {
    id: "interview",
    label: "インタビュー",
    badgeClassName: "bg-blue-500/90",
    heroClassName: "bg-gradient-to-br from-blue-500/25 via-indigo-500/10 to-emerald-400/10",
  },
];

export function isCategoryId(x: string): x is BlogCategoryId {
  return x === "guide" || x === "beginner" || x === "prediction" || x === "column" || x === "interview";
}

export function formatYmdToSlash(ymd: string): string {
  // "2025-12-19" -> "2025/12/19"
  return ymd.replaceAll("-", "/");
}

function contentRoot(): string {
  return path.join(process.cwd(), "content");
}

function blogDir(): string {
  return path.join(contentRoot(), "blog");
}

function factsDir(): string {
  return path.join(contentRoot(), "facts");
}

function readAllBlogFiles(): string[] {
  const dir = blogDir();
  if (!fs.existsSync(dir)) return [];
  const entries = fs.readdirSync(dir);
  return entries
    .filter((f) => f.endsWith(".mdx") || f.endsWith(".md"))
    .map((f) => path.join(dir, f));
}

function safeNumber(v: unknown, fallback: number): number {
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : fallback;
}

function safeString(v: unknown, fallback: string): string {
  return typeof v === "string" && v.trim() ? v.trim() : fallback;
}

function fileSlug(filePath: string): string {
  const base = path.basename(filePath);
  return base.replace(/\.mdx?$/i, "");
}

function categoryDecor(categoryId: BlogCategoryId) {
  const c = BLOG_CATEGORIES.find((x) => x.id === categoryId);
  return c
    ? { categoryLabel: c.label, badgeClassName: c.badgeClassName, heroClassName: c.heroClassName }
    : { categoryLabel: categoryId, badgeClassName: "bg-white/10", heroClassName: "bg-white/5" };
}

function normalizeFactsVisibility(v: unknown): "show" | "hide" {
  if (typeof v === "string" && v.trim().toLowerCase() === "hide") return "hide";
  return "show";
}

export function getAllPostMetas(opts?: { includeDraft?: boolean }): Array<BlogPostMeta & ReturnType<typeof categoryDecor>> {
  const includeDraft = opts?.includeDraft ?? false;

  const files = readAllBlogFiles();
  const metas = files.map((fp) => {
    // BOM耐性
    const raw = fs.readFileSync(fp, "utf8").replace(/^\uFEFF/, "");
    const parsed = matter(raw);

    const slug = fileSlug(fp);
    const title = safeString(parsed.data.title, slug);
    const description = safeString(parsed.data.description, "");
    const date = safeString(parsed.data.date, "2025-01-01");

    // 揺れ吸収: categoryId / category
    const categoryIdRaw = safeString((parsed.data.categoryId ?? parsed.data.category) as any, "column");
    const categoryId: BlogCategoryId = isCategoryId(categoryIdRaw) ? categoryIdRaw : "column";

    const minutes = safeNumber(parsed.data.minutes, 6);
    const views = safeNumber(parsed.data.views, 0);

    const draft = Boolean(parsed.data.draft);

    // 揺れ吸収: storeId / store
    const storeIdRaw =
      typeof parsed.data.storeId === "string"
        ? parsed.data.storeId
        : typeof parsed.data.store === "string"
          ? parsed.data.store
          : undefined;

    // 揺れ吸収: factsId / facts_id
    const factsIdRaw =
      typeof parsed.data.factsId === "string"
        ? parsed.data.factsId
        : typeof parsed.data.facts_id === "string"
          ? parsed.data.facts_id
          : undefined;

    // facts_visibility / factsVisibility
    const factsVisibilityRaw =
      typeof parsed.data.facts_visibility === "string"
        ? parsed.data.facts_visibility
        : typeof parsed.data.factsVisibility === "string"
          ? parsed.data.factsVisibility
          : undefined;

    const meta: BlogPostMeta = {
      slug,
      title,
      description,
      date,
      minutes,
      views,
      categoryId,
      draft,

      storeId: typeof storeIdRaw === "string" && storeIdRaw.trim() ? storeIdRaw.trim() : undefined,
      level: typeof parsed.data.level === "string" ? (parsed.data.level as any) : undefined,
      period: typeof parsed.data.period === "string" ? (parsed.data.period as any) : undefined,
      factsId: typeof factsIdRaw === "string" && factsIdRaw.trim() ? factsIdRaw.trim() : undefined,
      factsVisibility: normalizeFactsVisibility(factsVisibilityRaw),
    };

    return { ...meta, ...categoryDecor(categoryId) };
  });

  const filtered = includeDraft ? metas : metas.filter((m) => !m.draft);

  // デフォルトは新着順（date desc）
  filtered.sort((a, b) => (a.date < b.date ? 1 : -1));
  return filtered;
}

export function getPostBySlug(slug: string, opts?: { includeDraft?: boolean }): (BlogPost & ReturnType<typeof categoryDecor>) | null {
  const includeDraft = opts?.includeDraft ?? false;

  const fpMdx = path.join(blogDir(), `${slug}.mdx`);
  const fpMd = path.join(blogDir(), `${slug}.md`);

  const fp = fs.existsSync(fpMdx) ? fpMdx : fs.existsSync(fpMd) ? fpMd : null;
  if (!fp) return null;

  // BOM耐性
  const raw = fs.readFileSync(fp, "utf8").replace(/^\uFEFF/, "");
  const parsed = matter(raw);

  const title = safeString(parsed.data.title, slug);
  const description = safeString(parsed.data.description, "");
  const date = safeString(parsed.data.date, "2025-01-01");

  // 揺れ吸収: categoryId / category
  const categoryIdRaw = safeString((parsed.data.categoryId ?? parsed.data.category) as any, "column");
  const categoryId: BlogCategoryId = isCategoryId(categoryIdRaw) ? categoryIdRaw : "column";

  const minutes = safeNumber(parsed.data.minutes, 6);
  const views = safeNumber(parsed.data.views, 0);

  const draft = Boolean(parsed.data.draft);
  if (draft && !includeDraft) return null;

  // 揺れ吸収: storeId / store
  const storeIdRaw =
    typeof parsed.data.storeId === "string"
      ? parsed.data.storeId
      : typeof parsed.data.store === "string"
        ? parsed.data.store
        : undefined;

  // 揺れ吸収: factsId / facts_id
  const factsIdRaw =
    typeof parsed.data.factsId === "string"
      ? parsed.data.factsId
      : typeof parsed.data.facts_id === "string"
        ? parsed.data.facts_id
        : undefined;

  // facts_visibility / factsVisibility
  const factsVisibilityRaw =
    typeof parsed.data.facts_visibility === "string"
      ? parsed.data.facts_visibility
      : typeof parsed.data.factsVisibility === "string"
        ? parsed.data.factsVisibility
        : undefined;

  const post: BlogPost = {
    slug,
    title,
    description,
    date,
    minutes,
    views,
    categoryId,
    draft,

    storeId: typeof storeIdRaw === "string" && storeIdRaw.trim() ? storeIdRaw.trim() : undefined,
    level: typeof parsed.data.level === "string" ? (parsed.data.level as any) : undefined,
    period: typeof parsed.data.period === "string" ? (parsed.data.period as any) : undefined,
    factsId: typeof factsIdRaw === "string" && factsIdRaw.trim() ? factsIdRaw.trim() : undefined,
    factsVisibility: normalizeFactsVisibility(factsVisibilityRaw),

    mdx: parsed.content.trim(),
  };

  return { ...post, ...categoryDecor(categoryId) };
}

export function getFactsById(factsId: string): any | null {
  const fp = path.join(factsDir(), `${factsId}.json`);
  if (!fs.existsSync(fp)) return null;
  try {
    // BOM耐性
    const raw = fs.readFileSync(fp, "utf8").replace(/^\uFEFF/, "");
    return JSON.parse(raw);
  } catch {
    return null;
  }
}