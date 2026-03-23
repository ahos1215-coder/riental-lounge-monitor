import { z } from "zod";

/**
 * gray-matter の frontmatter を緩く検証（未知キーは passthrough）。
 * 失敗してもビルドは継続し、警告のみ（`BLOG_STRICT_FRONTMATTER=1` のときは例外）。
 */

const looseScalar = z.union([z.string(), z.number(), z.boolean()]).optional();

export const blogFrontmatterShapeSchema = z
  .object({
    title: looseScalar,
    description: looseScalar,
    date: looseScalar,
    categoryId: looseScalar,
    category: looseScalar,
    minutes: looseScalar,
    views: looseScalar,
    draft: z.union([z.boolean(), z.string(), z.number()]).optional(),
    storeId: looseScalar,
    store: looseScalar,
    factsId: looseScalar,
    facts_id: looseScalar,
    facts_visibility: looseScalar,
    factsVisibility: looseScalar,
    level: looseScalar,
    period: looseScalar,
  })
  .passthrough();

export function validateBlogFrontmatterShape(data: unknown, fileLabel: string): string[] {
  const r = blogFrontmatterShapeSchema.safeParse(data);
  if (r.success) return [];
  return r.error.issues.map((i) => `${fileLabel}: ${i.path.join(".") || "(root)"} — ${i.message}`);
}

/** YYYY-MM-DD 推奨（時刻付きでも許容） */
export function validateBlogDateFormat(dateStr: string, fileLabel: string): string | null {
  if (!dateStr || !String(dateStr).trim()) return `${fileLabel}: date が空です`;
  const s = String(dateStr).trim();
  if (!/^\d{4}-\d{2}-\d{2}/.test(s)) {
    return `${fileLabel}: date は YYYY-MM-DD で始まる形式を推奨（現値: ${s.slice(0, 40)}）`;
  }
  return null;
}
