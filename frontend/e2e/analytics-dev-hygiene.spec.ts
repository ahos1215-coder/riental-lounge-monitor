import { test, expect, ANALYTICS_HOST_RE } from "./fixtures";

// ────────────────────────────────────────────────────────────────────────────
// 開発者向けアナリティクス衛生管理の e2e 証跡。
//  - localhost（＝非本番ホスト）では、有効な測定 ID が設定されていても GA を一切ロード/発火しない。
//  - ?dev=1 は端末に永続オプトアウトフラグを保存し、gtag 公式の window['ga-disable-<ID>'] を立てる。
//  - ?dev=0 で解除する。UI 変化は無く、フィードバックは console.info の1行のみ。
//
// playwright.config.ts の webServer は NEXT_PUBLIC_GA_MEASUREMENT_ID=G-TEST00E2E0 を渡すため、
// 「ID があってもガードで GA ゼロ」を意味のある形で証明できる。GA 宛リクエストは fixtures 側で
// abort されるが、request イベント自体は発火するので「アプリが GA を発火しようとしていない」ことも観測できる。
// ────────────────────────────────────────────────────────────────────────────

const DEV_OPTOUT_KEY = "meguribi:ga-dev-optout";

function collectGaRequests(page: import("./fixtures").Page): string[] {
  const urls: string[] = [];
  page.on("request", (r) => {
    if (ANALYTICS_HOST_RE.test(r.url())) urls.push(r.url());
  });
  return urls;
}

function collectInfoLogs(page: import("./fixtures").Page): string[] {
  const logs: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "info") logs.push(m.text());
  });
  return logs;
}

test.describe("Analytics developer hygiene", () => {
  test("no GA is loaded or requested on a normal page load (localhost is non-production)", async ({
    page,
  }) => {
    const gaRequests = collectGaRequests(page);

    await page.goto("/store/nagasaki");
    await expect(page.locator("main")).toBeVisible();

    // gtag.js のスクリプトタグは本番ホストでしか注入されない → localhost では 0 本。
    await expect(
      page.locator('script[src*="googletagmanager.com/gtag/js"]'),
    ).toHaveCount(0);

    // gtag / dataLayer グローバルも存在しない。
    const hasGtag = await page.evaluate(
      () =>
        typeof (window as unknown as { gtag?: unknown }).gtag === "function" &&
        Array.isArray((window as unknown as { dataLayer?: unknown }).dataLayer),
    );
    expect(hasGtag).toBe(false);

    // GA ホスト宛のネットワークリクエストも 1 本も出ていない。
    expect(gaRequests).toEqual([]);
  });

  test("?dev=1 persists opt-out, arms ga-disable before any beacon, logs console.info, and stays GA-silent across SPA navigation", async ({
    page,
  }) => {
    const gaRequests = collectGaRequests(page);
    const infoLogs = collectInfoLogs(page);

    await page.goto("/store/nagasaki?dev=1");
    await expect(page.locator("main")).toBeVisible();

    // 端末単位の永続オプトアウトフラグが localStorage に保存される。
    await expect
      .poll(() => page.evaluate((k) => window.localStorage.getItem(k), DEV_OPTOUT_KEY))
      .toBe("1");

    // GA 公式オプトアウト window['ga-disable-<ID>'] が true になっている（beacon より前）。
    await expect
      .poll(() =>
        page.evaluate(() => {
          const w = window as unknown as Record<string, unknown>;
          const keys = Object.keys(w).filter((k) => k.startsWith("ga-disable-"));
          return keys.length > 0 && keys.every((k) => w[k] === true);
        }),
      )
      .toBe(true);

    // フィードバックは console.info の1行のみ。
    expect(
      infoLogs.some((t) => t.includes("[analytics]") && t.includes("オプトアウトを有効化")),
    ).toBe(true);

    // クライアントサイド遷移（SPA）を挟んでもフラグは持続し、GA は沈黙のまま。
    await page.getByRole("link", { name: "めぐりび" }).first().click();
    await expect(page).toHaveURL(/\/$|\/\?/);
    await expect(page.locator("header")).toBeVisible();

    await expect
      .poll(() => page.evaluate((k) => window.localStorage.getItem(k), DEV_OPTOUT_KEY))
      .toBe("1");

    await expect(
      page.locator('script[src*="googletagmanager.com/gtag/js"]'),
    ).toHaveCount(0);
    expect(gaRequests).toEqual([]);
  });

  test("?dev=0 clears the opt-out flag and logs the re-enable console.info", async ({ page }) => {
    const infoLogs = collectInfoLogs(page);

    // まず opt-out 状態にする。
    await page.goto("/store/nagasaki?dev=1");
    await expect
      .poll(() => page.evaluate((k) => window.localStorage.getItem(k), DEV_OPTOUT_KEY))
      .toBe("1");

    // ?dev=0 で解除。
    await page.goto("/store/nagasaki?dev=0");
    await expect
      .poll(() => page.evaluate((k) => window.localStorage.getItem(k), DEV_OPTOUT_KEY))
      .toBeNull();

    expect(
      infoLogs.some((t) => t.includes("[analytics]") && t.includes("オプトアウトを解除")),
    ).toBe(true);
  });
});
