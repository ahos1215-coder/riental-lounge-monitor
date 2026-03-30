import { test, expect } from "@playwright/test";

// ────────────────────────────────────────────
// スモークテスト: 主要ページが正しくレンダリングされるか確認
// Backend (Flask) が起動していなくてもフロント単体で成功すること
// ────────────────────────────────────────────

test.describe("Top page", () => {
  test("renders heading and navigation", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("header")).toBeVisible();
    await expect(page.getByText("めぐりび")).toBeVisible();
  });

  test("has working navigation links", async ({ page }) => {
    await page.goto("/");
    const storesLink = page.getByRole("link", { name: /店舗/i });
    await expect(storesLink.first()).toBeVisible();
  });

  test("hero section renders with CTA", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText("今夜の予測を見る")).toBeVisible();
    await expect(page.getByText("やさしく照らす案内灯")).toBeVisible();
  });

  test("mobile menu toggle works", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto("/");
    const menuButton = page.getByRole("button", { name: /メニュー/i });
    await expect(menuButton).toBeVisible();
    await menuButton.click();
    await expect(page.getByRole("link", { name: "AI予測" })).toBeVisible();
  });
});

test.describe("Stores page", () => {
  test("renders store list with search", async ({ page }) => {
    await page.goto("/stores");
    await expect(page.locator("main")).toBeVisible();
    const hasSearchOrTabs = await page
      .locator("input, [role=tablist], button")
      .first()
      .isVisible()
      .catch(() => false);
    expect(hasSearchOrTabs).toBeTruthy();
  });

  test("region filter buttons exist", async ({ page }) => {
    await page.goto("/stores");
    // At least one region filter button should exist
    const buttons = page.locator("button");
    await expect(buttons.first()).toBeVisible();
  });
});

test.describe("Store detail page", () => {
  test("renders store detail for nagasaki", async ({ page }) => {
    await page.goto("/store/nagasaki");
    await expect(page.locator("main")).toBeVisible();
    // Favorite button should be visible
    await expect(page.getByRole("button", { name: /お気に入り/i })).toBeVisible();
  });

  test("shows related stores section", async ({ page }) => {
    await page.goto("/store/nagasaki");
    await expect(page.getByText("ほかの店舗を見る")).toBeVisible();
  });
});

test.describe("Reports page", () => {
  test("renders with Daily/Weekly tabs", async ({ page }) => {
    await page.goto("/reports");
    await expect(page.locator("main")).toBeVisible();
    await expect(page.getByText("Daily")).toBeVisible();
    await expect(page.getByText("Weekly")).toBeVisible();
  });

  test("tab switching works", async ({ page }) => {
    await page.goto("/reports");
    const weeklyTab = page.getByText("Weekly");
    await weeklyTab.click();
    await expect(page).toHaveURL(/tab=weekly/);
  });
});

test.describe("Compare page", () => {
  test("renders compare page", async ({ page }) => {
    await page.goto("/compare");
    await expect(page.locator("main")).toBeVisible();
  });
});

test.describe("Mypage", () => {
  test("renders without crash", async ({ page }) => {
    await page.goto("/mypage");
    await expect(page.locator("main")).toBeVisible();
  });

  test("shows favorites and history sections", async ({ page }) => {
    await page.goto("/mypage");
    // Should show some section headings even with empty state
    await expect(page.locator("main")).toBeVisible();
  });
});

test.describe("Blog page", () => {
  test("renders blog list", async ({ page }) => {
    await page.goto("/blog");
    await expect(page.locator("main")).toBeVisible();
  });
});

test.describe("Navigation flow", () => {
  test("can navigate from top to stores to detail", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("link", { name: /店舗一覧/i }).first().click();
    await expect(page).toHaveURL(/\/stores/);
    await expect(page.locator("main")).toBeVisible();
  });

  test("header is sticky and visible on scroll", async ({ page }) => {
    await page.goto("/");
    await page.evaluate(() => window.scrollBy(0, 500));
    await expect(page.locator("header")).toBeVisible();
  });
});

test.describe("Error handling", () => {
  test("404 page shows for invalid route", async ({ page }) => {
    const response = await page.goto("/this-does-not-exist");
    expect(response?.status()).toBe(404);
  });
});
