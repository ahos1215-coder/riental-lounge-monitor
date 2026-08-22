// frontend/src/lib/sw.cachePolicy.test.ts
//
// public/sw.js のキャッシュ許可判定ロジックの番犬テスト。
// 2026-08-22 総合レビュー対応（検証記録は memory/general-review-2026-08-22.md）:
// 以前の sw.js は「/api/ と別オリジン以外の全GET」をキャッシュ候補にしていた
// （RSC payload・動的HTML・404/500まで保存し得た）。許可リスト方式へ反転した際の
// 判定ロジック（isCacheableStaticAssetPath / isRscOrDynamicRequest）を固定する。
//
// public/ はビルドパイプラインを通らない静的ファイルで ESM import ができないため、
// vitest.config.ts の environment: "node" のもとで CJS require で直接読み込む
// （sw.js 側は `module.exports` を持つが、実際の Service Worker 実行環境には
// `self` はあっても `module` が無いため、その分岐は SW では絶対に実行されない）。
import { createRequire } from "node:module";
import path from "node:path";
import { describe, expect, it } from "vitest";

const require = createRequire(import.meta.url);
const swPolicy = require(path.resolve(__dirname, "../../public/sw.js")) as {
  isCacheableStaticAssetPath: (pathname: string) => boolean;
  isRscOrDynamicRequest: (
    url: URL,
    headers: { get(name: string): string | null } | null | undefined,
  ) => boolean;
};

function headersOf(accept?: string) {
  return { get: (name: string) => (name.toLowerCase() === "accept" ? (accept ?? null) : null) };
}

describe("isCacheableStaticAssetPath", () => {
  it("Next.js のビルド成果物はキャッシュ対象", () => {
    expect(swPolicy.isCacheableStaticAssetPath("/_next/static/chunks/main-abc123.js")).toBe(true);
  });

  it("フォントファイルはキャッシュ対象", () => {
    expect(swPolicy.isCacheableStaticAssetPath("/fonts/inter.woff2")).toBe(true);
    expect(swPolicy.isCacheableStaticAssetPath("/fonts/inter.ttf")).toBe(true);
  });

  it("favicon.ico と /icons/ 配下はキャッシュ対象", () => {
    expect(swPolicy.isCacheableStaticAssetPath("/favicon.ico")).toBe(true);
    expect(swPolicy.isCacheableStaticAssetPath("/icons/icon-192.png")).toBe(true);
  });

  it("店舗ページ等の動的HTMLはキャッシュ対象外", () => {
    expect(swPolicy.isCacheableStaticAssetPath("/store/shibuya")).toBe(false);
    expect(swPolicy.isCacheableStaticAssetPath("/")).toBe(false);
    expect(swPolicy.isCacheableStaticAssetPath("/reports/daily/shibuya")).toBe(false);
  });

  it("/api/ 配下は fetch ハンドラの手前で弾かれる前提だが、この関数単体でも対象外", () => {
    expect(swPolicy.isCacheableStaticAssetPath("/api/range")).toBe(false);
  });
});

describe("isRscOrDynamicRequest", () => {
  it("?_rsc= クエリ付きは RSC payload と判定する", () => {
    const url = new URL("https://example.com/store/shibuya?_rsc=abc123");
    expect(swPolicy.isRscOrDynamicRequest(url, headersOf())).toBe(true);
  });

  it("Accept: text/x-component は RSC payload と判定する", () => {
    const url = new URL("https://example.com/store/shibuya");
    expect(swPolicy.isRscOrDynamicRequest(url, headersOf("text/x-component"))).toBe(true);
  });

  it("通常のHTMLナビゲーション相当のリクエストは RSC ではない", () => {
    const url = new URL("https://example.com/store/shibuya");
    expect(swPolicy.isRscOrDynamicRequest(url, headersOf("text/html"))).toBe(false);
  });

  it("headers が無くても例外にならない", () => {
    const url = new URL("https://example.com/store/shibuya");
    expect(swPolicy.isRscOrDynamicRequest(url, null)).toBe(false);
  });
});
