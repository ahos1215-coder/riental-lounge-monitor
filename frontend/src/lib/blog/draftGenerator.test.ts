import { describe, expect, it } from "vitest";

import { normalizeMdxForBlog } from "./draftGenerator";

describe("normalizeMdxForBlog", () => {
  it("normalizes leading --- frontmatter without leading prose", () => {
    const raw = `---\ntitle: "テスト"\ndescription: "説明"\ndate: "2026-03-25"\n---\n\n## 見出し\n本文です。`;
    const out = normalizeMdxForBlog(raw);
    expect(out.startsWith("---\n")).toBe(true);
    expect(out).toContain("title:");
    expect(out).toContain("## 見出し");
  });

  it("unwraps fenced markdown blocks", () => {
    const raw =
      "```mdx\n---\ntitle: \"x\"\ndescription: \"y\"\ndate: \"2026-01-01\"\ncategoryId: \"column\"\nlevel: \"normal\"\nstore: \"店\"\nfacts_id: \"f\"\nfacts_visibility: \"show\"\n---\n\n## A\n" +
      "B".repeat(50) +
      "\n```";
    const out = normalizeMdxForBlog(raw);
    expect(out.startsWith("---")).toBe(true);
    expect(out).not.toContain("```");
  });
});
