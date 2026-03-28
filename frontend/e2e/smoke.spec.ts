import { test, expect } from "@playwright/test";

// ────────────────────────────────────────────
// スモークテスト: 主要ページが正しくレンダリングされるか確認
// Backend (Flask) が起動していなくてもフロント単体で成功すること
// ────────────────────────────────────────────

test.describe("Top page", () => {
  test("renders heading and navigation", async ({ page }) => {
    await page.goto("/");
    // ヘッダーが表示される
    await expect(page.locator("header")).toBeVisible();
    // めぐりび関連のテキストが存在する
    await expect(page.getByText("めぐりび")).toBeVisible();
  });

  test("has working navigation links", async ({ page }) => {
    await page.goto("/");
    // 店舗一覧リンクが存在する
    const storesLink = page.getByRole("link", { name: /店舗/i });
    await expect(storesLink.first()).toBeVisible();
  });
});

test.describe("Stores page", () => {
  test("renders store list with search", async ({ page }) => {
    await page.goto("/stores");
    // ページタイトルまたは見出しが存在する
    await expect(page.locator("main")).toBeVisible();
    // 検索エリアのテキスト入力 or タブが存在する
    const hasSearchOrTabs = await page
      .locator("input, [role=tablist], button")
      .first()
      .isVisible()
      .catch(() => false);
    expect(hasSearchOrTabs).toBeTruthy();
  });
});

test.describe("Reports page", () => {
  test("renders with Daily/Weekly tabs", async ({ page }) => {
    await page.goto("/reports");
    await expect(page.locator("main")).toBeVisible();
    // Daily / Weekly タブが存在する
    await expect(page.getByText("Daily")).toBeVisible();
    await expect(page.getByText("Weekly")).toBeVisible();
  });

  test("tab switching works", async ({ page }) => {
    await page.goto("/reports");
    const weeklyTab = page.getByText("Weekly");
    await weeklyTab.click();
    // URL が tab=weekly を含む
    await expect(page).toHaveURL(/tab=weekly/);
  });
});

test.describe("Mypage", () => {
  test("renders without crash", async ({ page }) => {
    await page.goto("/mypage");
    await expect(page.locator("main")).toBeVisible();
  });
});

test.describe("Blog page", () => {
  test("renders blog list", async ({ page }) => {
    await page.goto("/blog");
    await expect(page.locator("main")).toBeVisible();
  });
});
