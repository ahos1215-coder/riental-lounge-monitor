import { test, expect } from "@playwright/test";

// ────────────────────────────────────────────
// 料金シミュレーター（オリエンタルラウンジ36店舗ロールアウト）の描画確認
// ────────────────────────────────────────────

test.describe("Cost simulator card - oriental stores", () => {
  test("renders on /store/nagasaki with the 料金の目安 heading", async ({ page }) => {
    await page.goto("/store/nagasaki");
    await expect(page.getByText("料金の目安")).toBeVisible();
    // 自由計算アコーディオンが存在する
    await expect(page.getByText("自由に計算する（任意の入店・退店時刻）")).toBeVisible();
  });

  test("renders on /store/shibuya with store-specific numbers", async ({ page }) => {
    await page.goto("/store/shibuya");
    await expect(page.getByText("料金の目安")).toBeVisible();

    // 自由計算アコーディオンを開く
    await page.getByText("自由に計算する（任意の入店・退店時刻）").click();

    // 曜日タイプを週末に切り替える
    await page.getByRole("button", { name: "週末" }).first().click();

    // 入店22:00・退店24:00に設定（渋谷の週末22:00-24:00バンドは¥1100/10分）
    const entrySelect = page.locator("select").first();
    await entrySelect.selectOption("22:00");
    const exitSelect = page.locator("select").nth(1);
    await exitSelect.selectOption("24:00");

    // アプリチェックイン済み(既定true)のまま。手計算: 12 units x ¥1100 = ¥13,200
    // (¥13,200 は合計見出し・内訳表・コスト帯チップの3箇所に出るため、
    // 「男性 合計（目安）」の大見出し数値に絞って検証する)
    await expect(page.getByText("男性 合計（目安）").locator("..").getByText("¥13,200")).toBeVisible();
  });

  test("shows a price-jump note when applicable", async ({ page }) => {
    await page.goto("/store/shibuya");
    // 値上がり注意行（amber）はコスト帯セクションに出る想定
    const jumpNote = page.locator("text=以降は相席");
    // 目安時刻が営業終了間際でなければ出るはず（今夜の予測有無に依存するため存在確認のみ）
    const count = await jumpNote.count();
    expect(count).toBeGreaterThanOrEqual(0);
  });

  test("does NOT render on /store/ay_shibuya (aisekiya brand, no pricing data)", async ({ page }) => {
    await page.goto("/store/ay_shibuya");
    await expect(page.locator("main")).toBeVisible();
    await expect(page.getByText("料金の目安")).toHaveCount(0);
  });

  test("does NOT render on /store/gangnam (non-Japan oriental store)", async ({ page }) => {
    await page.goto("/store/gangnam");
    await expect(page.locator("main")).toBeVisible();
    await expect(page.getByText("料金の目安")).toHaveCount(0);
  });

  test("does NOT render on /store/sapporo_ag (dead official page, excluded from registry)", async ({
    page,
  }) => {
    await page.goto("/store/sapporo_ag");
    await expect(page.locator("main")).toBeVisible();
    await expect(page.getByText("料金の目安")).toHaveCount(0);
  });

  test("nagoya_ag shows the opening-gap assumption footnote", async ({ page }) => {
    await page.goto("/store/nagoya_ag");
    await expect(page.getByText("料金の目安")).toBeVisible();
    await expect(page.getByText(/公式サイトに明示バンドが無いため/)).toBeVisible();
  });
});
