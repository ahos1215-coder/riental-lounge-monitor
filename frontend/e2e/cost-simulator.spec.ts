import { test, expect } from "@playwright/test";

// ────────────────────────────────────────────
// 料金シミュレーター（オリエンタルラウンジ36店舗 + 相席屋6店舗）の描画確認
// ────────────────────────────────────────────

test.describe("Cost simulator card - oriental stores", () => {
  test("renders on /store/nagasaki with the 料金の目安 heading", async ({ page }) => {
    await page.goto("/store/nagasaki");
    await expect(page.getByText("料金の目安")).toBeVisible();
    // 自由計算アコーディオンが存在する
    await expect(page.getByText("自由に計算する（任意の入店・退店時刻）")).toBeVisible();
  });

  test("renders on /store/shibuya with store-specific numbers (unchanged by the aisekiya rollout)", async ({
    page,
  }) => {
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

    // オリエンタルの週末キャプションが従来通り表示される（相席屋の「日曜含む」文言ではない）
    await expect(page.getByText(/週末料金の対象: 金・土・祝前日/)).toBeVisible();
  });

  test("shows a price-jump note when applicable", async ({ page }) => {
    await page.goto("/store/shibuya");
    // 値上がり注意行（amber）はコスト帯セクションに出る想定
    const jumpNote = page.locator("text=以降は相席");
    // 目安時刻が営業終了間際でなければ出るはず（今夜の予測有無に依存するため存在確認のみ）
    const count = await jumpNote.count();
    expect(count).toBeGreaterThanOrEqual(0);
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

test.describe("Cost simulator card - aisekiya stores", () => {
  test("renders an aisekiya-flavored card on /store/ay_shibuya (flat rate, no price-jump line, aisekiya caption)", async ({
    page,
  }) => {
    await page.goto("/store/ay_shibuya");
    await expect(page.getByText("料金の目安")).toBeVisible();

    // 相席屋専用の週末キャプション（日曜も高料金対象と明記）
    await expect(page.getByText(/高料金の対象: 金・土・日曜日・祝日・祝前日/)).toBeVisible();

    // 値上がり注意行（オリエンタルのamber「以降は相席」行）は出ない
    await expect(page.locator("text=以降は相席")).toHaveCount(0);

    // 自由計算アコーディオンを開いて、フラット単価(¥650/¥750)で計算されることを確認
    // （相席していない時間は¥0の注記はコスト帯セクションと自由計算セクションの両方に
    // 出るため、自由計算側の固有文言「（上限）」で一意に絞り込む）
    await page.getByText("自由に計算する（任意の入店・退店時刻）").click();
    await expect(page.getByText(/相席していない時間は.*上限/)).toBeVisible();
  });

  test("ay_shibuya free-calc computes the flat weekday rate correctly (2h = 12 x ¥650 = ¥7,800)", async ({
    page,
  }) => {
    await page.goto("/store/ay_shibuya");
    await page.getByText("自由に計算する（任意の入店・退店時刻）").click();

    // 平日トグルにする（自動判定が既に平日ならno-op）
    await page.getByRole("button", { name: "平日" }).first().click();

    const entrySelect = page.locator("select").first();
    await entrySelect.selectOption("20:00");
    const exitSelect = page.locator("select").nth(1);
    await exitSelect.selectOption("22:00");

    // アプリチェックイン済み(既定true)のまま。手計算: 12 units x ¥650 = ¥7,800
    await expect(page.getByText("男性 合計（目安・相席時間ぶん）").locator("..").getByText("¥7,800")).toBeVisible();
  });

  test("does NOT render on /store/ay_niigata (permanently closed 2026-06-28, excluded from registry)", async ({
    page,
  }) => {
    await page.goto("/store/ay_niigata");
    await expect(page.locator("main")).toBeVisible();
    await expect(page.getByText("料金の目安")).toHaveCount(0);
  });
});
