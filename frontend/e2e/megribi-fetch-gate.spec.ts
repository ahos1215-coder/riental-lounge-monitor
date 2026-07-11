import { test, expect } from "@playwright/test";

// ────────────────────────────────────────────
// 判定表示OFF後の /api/megribi_score フェッチ遮断（bug rank7）の回帰テスト。
//
// SHOW_MEGRIBI_JUDGMENTS=false (featureFlags.ts) の間は判定バッジ／TOP5／比較ラベルが
// すべて非表示のため、それらを裏で支える /api/megribi_score フェッチ自体も
// home-client.tsx / app/page.tsx / stores-list-client.tsx / compare-client.tsx の
// 4経路すべてで発火してはいけない（バックエンドの無駄な Supabase fan-out を防ぐ）。
// フラグを true に戻せば、このテストはそのまま「取得が復活したこと」の検知にも使える
// （その場合はこのテストを更新すること）。
// ────────────────────────────────────────────

function collectMegribiScoreRequests(page: import("@playwright/test").Page): string[] {
  const hits: string[] = [];
  page.on("request", (req) => {
    if (req.url().includes("/api/megribi_score")) {
      hits.push(req.url());
    }
  });
  return hits;
}

test.describe("megribi_score fetch gate (SHOW_MEGRIBI_JUDGMENTS=false)", () => {
  test("home (/) fires zero /api/megribi_score requests", async ({ page }) => {
    const hits = collectMegribiScoreRequests(page);
    await page.goto("/");
    // ホームの初期描画・クライアント fetch が一巡するのを待つ
    await expect(page.getByRole("link", { name: "めぐりび" }).first()).toBeVisible();
    await page.waitForTimeout(1000);
    expect(hits).toEqual([]);
  });

  test("stores (/stores) fires zero /api/megribi_score requests", async ({ page }) => {
    const hits = collectMegribiScoreRequests(page);
    await page.goto("/stores");
    await expect(page.locator("section").first()).toBeVisible();
    // 一覧カードの range/forecast 取得が一巡するのを待つ
    await page.waitForTimeout(1500);
    expect(hits).toEqual([]);
  });

  test("compare (/compare?stores=...) fires zero /api/megribi_score requests", async ({ page }) => {
    const hits = collectMegribiScoreRequests(page);
    // 店舗を2件 URL 指定して選択済み状態で開く（比較カードの fetch エフェクトを確実に起動させる）
    await page.goto("/compare?stores=nagasaki,fukuoka");
    await expect(page.locator("main")).toBeVisible();
    await page.waitForTimeout(1500);
    expect(hits).toEqual([]);
  });
});
