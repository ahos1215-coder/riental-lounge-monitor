import { defineConfig, devices } from "@playwright/test";

const PORT = process.env.PORT ?? "3000";
const BASE_URL = process.env.PLAYWRIGHT_BASE_URL ?? `http://localhost:${PORT}`;

// e2e 用のダミー GA 測定 ID。localhost（=非本番ホスト）では GA は本番ガードで無効化されるため、
// この ID が設定されていても gtag はロード/発火しない。それでも設定しておくことで
// 「有効な ID があっても localhost では計測ゼロ」を証明でき、?dev の ga-disable 反映も検証できる。
// 本番の実 ID とは別物なので、万一リクエストが漏れても実プロパティを汚さない（fixtures 側でも abort）。
const E2E_GA_TEST_ID = "G-TEST00E2E0";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? "github" : "html",
  timeout: 30_000,

  use: {
    baseURL: BASE_URL,
    trace: "on-first-retry",
  },

  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],

  webServer: process.env.PLAYWRIGHT_BASE_URL
    ? undefined
    : {
        command: "npm run dev",
        port: Number(PORT),
        reuseExistingServer: !process.env.CI,
        timeout: 60_000,
        env: { NEXT_PUBLIC_GA_MEASUREMENT_ID: E2E_GA_TEST_ID },
      },
});
