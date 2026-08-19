import { test, expect } from "./fixtures";

// ────────────────────────────────────────────
// エリアハブ（/area/[area]）のスモーク。Backend が無くても成立する静的部分だけを見る。
// SEO Phase3-C/D の「発見最優先」方針を e2e で固定する:
//  - 単独オリエンタル店エリア（相席屋の店舗がサイトに無い地名）には
//    「相席屋・相席ラウンジをお探しの方へ」の正直な案内文が出る
//  - 両ブランドが在籍するエリア（渋谷）にはその案内文を出さない
//  - 未登録エリアは real 404
// ────────────────────────────────────────────

test.describe("Area hub page", () => {
  test("単独オリエンタル店エリア（静岡）: 見出し・店舗リンク・相席屋で探す人向け案内が出る", async ({ page }) => {
    await page.goto("/area/shizuoka");
    await expect(page.getByRole("heading", { level: 1 })).toContainText("静岡の相席ラウンジ");
    await expect(page.getByRole("link", { name: /オリエンタルラウンジ 静岡/ }).first()).toBeVisible();
    await expect(page.getByRole("heading", { name: /相席屋・相席ラウンジをお探しの方へ/ })).toBeVisible();
    // 「同じ店」とは書かない（別ブランドと明記）
    await expect(page.getByText(/相席屋とオリエンタルラウンジは別ブランド/)).toBeVisible();
    // 他エリア・全店舗一覧への導線
    await expect(page.getByRole("link", { name: /全店舗一覧/ })).toBeVisible();
  });

  test("両ブランド在籍エリア（渋谷）: 相席屋で探す人向け案内は出さない・両店を列挙", async ({ page }) => {
    await page.goto("/area/shibuya");
    await expect(page.getByRole("heading", { level: 1 })).toContainText("渋谷の相席ラウンジ");
    await expect(page.getByRole("heading", { name: /相席屋・相席ラウンジをお探しの方へ/ })).toHaveCount(0);
    await expect(page.getByRole("link", { name: /相席屋 渋谷/ }).first()).toBeVisible();
    await expect(page.getByRole("link", { name: /オリエンタルラウンジ 渋谷/ }).first()).toBeVisible();
  });

  test("長崎（Phase3-Dで追加）が存在し、未登録エリアは404", async ({ page }) => {
    const ok = await page.goto("/area/nagasaki");
    expect(ok?.status()).toBe(200);
    await expect(page.getByRole("heading", { level: 1 })).toContainText("長崎の相席ラウンジ");

    const res = await page.goto("/area/not-an-area");
    expect(res?.status()).toBe(404);
  });

  test("店舗ページの静的ナビからエリアハブへ戻れる", async ({ page }) => {
    await page.goto("/store/shizuoka");
    const link = page.getByRole("link", { name: /静岡の相席ラウンジ一覧/ });
    await expect(link).toBeVisible();
    await link.click();
    await expect(page).toHaveURL(/\/area\/shizuoka$/);
  });
});
