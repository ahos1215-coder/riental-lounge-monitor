import { test as base, expect, type Page } from "@playwright/test";

/**
 * すべての e2e / ブラウザ検証トラフィックについて、GA（googletagmanager.com /
 * google-analytics.com / analytics.google.com）宛のリクエストを abort する。
 * これは自動チェックの通信でオーナーの GA データを汚さないための保険。
 *
 * 各 spec は `@playwright/test` の代わりにこのファイルの `test` を import するだけでよい
 * （route は page fixture で自動的に仕込まれる）。abort しても request イベント自体は
 * 発火するため、「アプリが GA を発火しようとしていないこと」を別途 page.on("request") で
 * 観測する検証（analytics-dev-hygiene.spec.ts）とも両立する。
 */

export const ANALYTICS_HOST_RE = /googletagmanager\.com|google-analytics\.com|analytics\.google\.com/;

/** 指定ページの GA 宛リクエストを abort する（fixture 未経由で使いたい時のヘルパ）。 */
export async function blockAnalytics(page: Page): Promise<void> {
  await page.route(ANALYTICS_HOST_RE, (route) => route.abort());
}

export const test = base.extend({
  page: async ({ page }, use) => {
    await blockAnalytics(page);
    await use(page);
  },
});

export { expect };
export type { Page } from "@playwright/test";
