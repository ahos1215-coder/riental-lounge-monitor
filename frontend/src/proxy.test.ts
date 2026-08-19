import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

/**
 * 番犬テスト（D-15）: proxy.ts の手書き一覧 FILESYSTEM_BLOG_SLUGS と
 * frontend/content/blog/*.mdx の実ファイルが一致していることを固定する。
 *
 * proxy.ts はリクエストごとに fs を読まないため一覧を静的に持っている。ここがズレると
 * 新しい記事が「存在しない slug」と判定され、/blog/[slug] が 404 に rewrite される
 * （＝公開したはずの記事が読めなくなる）。追記漏れをコメントの注意書きだけに頼らない。
 *
 * proxy.ts は Next.js のファイル規約（middleware 相当）なので、テストのために
 * export を増やさず、ソースの Set リテラルを読み取って突き合わせる。
 */

const REPO_FRONTEND = path.resolve(__dirname, "..");

function readDeclaredSlugs(): string[] {
  const src = fs.readFileSync(path.join(REPO_FRONTEND, "src/proxy.ts"), "utf-8");
  const block = src.match(/const FILESYSTEM_BLOG_SLUGS = new Set\(\[([\s\S]*?)\]\)/);
  expect(block, "proxy.ts の FILESYSTEM_BLOG_SLUGS 定義が見つからない（形が変わった？）").toBeTruthy();
  return Array.from(block![1].matchAll(/"([^"]+)"/g), (m) => m[1]);
}

function readActualSlugs(): string[] {
  return fs
    .readdirSync(path.join(REPO_FRONTEND, "content/blog"), { withFileTypes: true })
    .filter((e) => e.isFile() && e.name.endsWith(".mdx"))
    .map((e) => e.name.replace(/\.mdx$/, ""));
}

describe("proxy.ts の FILESYSTEM_BLOG_SLUGS", () => {
  it("content/blog/*.mdx の一覧と完全に一致する（新規記事の追記漏れ検知）", () => {
    const declared = readDeclaredSlugs().sort();
    const actual = readActualSlugs().sort();
    expect(declared).toEqual(actual);
  });

  it("空でもなく重複もしていない", () => {
    const declared = readDeclaredSlugs();
    expect(declared.length).toBeGreaterThan(0);
    expect(new Set(declared).size).toBe(declared.length);
  });
});
