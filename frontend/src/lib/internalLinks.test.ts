import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

/**
 * 番犬テスト（2026-08-26 計測レビューR2対応・新規）。
 *
 * レビュー§5-5: 内部リンクが `/store/${slug}?store=${slug}` という非正規URLを生成していた
 * 箇所が10件あった（`/store/[id]` は path slug を優先し query は読まれない・canonical は
 * 既に `/store/<slug>`）。今回それらを全て `/store/<slug>` に統一したが、コメントの注意書きだけに
 * 頼ると再発を防げないため、実ソースを走査して固定する（合成フィクスチャではなく実ファイル検査）。
 *
 * 外部から届く古い `?store=` 付きURLへの後方互換は変えていない（query が無視されるだけ）。
 * ここが検査するのは「内部でこれから新しく作るリンク」だけ。
 */

const SRC_ROOT = path.resolve(__dirname, "..");

// `/store/${...}?store=` の形（テンプレートリテラル内の式は中身を問わない）と、
// `/store/slug-like?store=` のような静的リテラルだけを禁止する。空白や日本語を含む
// 文字クラスにすると、文章中に偶然「/store/[id] ... ?store=」のような地の文が現れた場合に
// 誤検知するため、スラグに現れうる語構成文字（`\w` とハイフン）だけに絞る。
const STORE_QUERY_PATTERN = /\/store\/(?:\$\{[^}]*\}|[\w-]+)\?store=/;

function collectSourceFiles(dir: string, acc: string[] = []): string[] {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.name === "node_modules" || entry.name.startsWith(".")) continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      collectSourceFiles(full, acc);
    } else if (entry.isFile() && /\.(tsx?|mjs)$/.test(entry.name) && !entry.name.endsWith(".test.ts")) {
      acc.push(full);
    }
  }
  return acc;
}

describe("internal /store/ links never append ?store=", () => {
  it("finds zero occurrences of /store/<slug>?store= across frontend/src", () => {
    const files = collectSourceFiles(SRC_ROOT);
    const offenders: string[] = [];
    for (const file of files) {
      const content = fs.readFileSync(file, "utf-8");
      if (STORE_QUERY_PATTERN.test(content)) {
        offenders.push(path.relative(SRC_ROOT, file));
      }
    }
    expect(offenders, `?store= 付きの内部 /store/ リンクが見つかった: ${offenders.join(", ")}`).toEqual(
      [],
    );
  });
});
