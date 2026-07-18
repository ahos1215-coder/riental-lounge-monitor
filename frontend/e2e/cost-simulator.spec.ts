import { test, expect } from "./fixtures";

// ────────────────────────────────────────────
// 料金シミュレーター（オリエンタルラウンジ37店舗 + 相席屋5店舗）の描画確認
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

  test("shows a deterministic price-jump note when no live forecast is available", async ({ page }) => {
    // 旧実装は「count >= 0」という常に真になる空アサーションで、実質何もテストしていなかった
    // （目安時刻が実際の予測有無に依存し、実行タイミングでノートの有無が変わるため存在確認だけで
    // 逃げていた）。forecast_today/forecast_snapshot を「予測なし」に固定して hasForecast=false の
    // フォールバック（22:00入店の例示アンカー）を強制すれば、決定論的に検証できる。
    await page.route("**/api/forecast_today?**", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, data: [] }) }),
    );
    await page.route("**/api/forecast_snapshot?**", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: false }) }),
    );

    await page.goto("/store/shibuya");
    await expect(page.getByText("料金の目安")).toBeVisible();

    // 予測なし固定なら入店目安は例示アンカー22:00（渋谷の開店18:00より後なので採用される）。
    // 22:00の次に到達するバンドは「24時〜6時」（平日¥880/週末¥1,200、渋谷raw.tsで確認済み）で、
    // 平日・週末どちらの値でも非nullのため曜日タイプ（実行日依存）に関わらず必ず表示される。
    await expect(page.getByText(/24:00 以降は相席 10分 ¥(880|1,200)/)).toBeVisible();
  });

  test("does NOT render on /store/gangnam (non-Japan oriental store)", async ({ page }) => {
    await page.goto("/store/gangnam");
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
  test("renders an aisekiya-flavored card on /store/ay_shibuya (aisekiya caption + 22:00 surcharge jump line)", async ({
    page,
  }) => {
    await page.goto("/store/ay_shibuya");
    await expect(page.getByText("料金の目安")).toBeVisible();

    // 相席屋専用の週末キャプション（日曜も高料金対象と明記）
    await expect(page.getByText(/高料金の対象: 金・土・日曜日・祝日・祝前日/)).toBeVisible();

    // 22:00以降の10%加算をオリエンタルと同じ「値上がり注意行」で表示する
    // （¥650×1.1=¥715 平日 / ¥750×1.1=¥825 週末。オリエンタルの「XX時以降は相席」とは
    // 別文言「22:00以降は相席」）。曜日タイプは自動判定＝実行日に依存するため、¥715固定だと
    // 週末実行時に必ず落ちる。平日/週末どちらの値も許容する。
    await expect(page.getByText(/22:00以降は相席 10分 ¥(715|825)/)).toBeVisible();

    // 自由計算アコーディオンを開いて、相席していない時間は¥0の注記（自由計算側の固有文言「（上限）」）を確認
    await page.getByText("自由に計算する（任意の入店・退店時刻）").click();
    await expect(page.getByText(/相席していない時間は.*上限/)).toBeVisible();
  });

  test("ay_shibuya free-calc: pre-22:00 stay is flat ¥650 (20:00-22:00 = 12 x ¥650 = ¥7,800)", async ({
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

    // アプリチェックイン済み(既定true)のまま。全ユニットが22:00前=加算なし。手計算: 12 x ¥650 = ¥7,800
    await expect(page.getByText("男性 合計（目安・相席時間ぶん）").locator("..").getByText("¥7,800")).toBeVisible();
  });

  test("ay_shibuya free-calc: a stay past 22:00 reflects the 10% surcharge (21:30-23:30 weekday = ¥8,385)", async ({
    page,
  }) => {
    await page.goto("/store/ay_shibuya");
    await page.getByText("自由に計算する（任意の入店・退店時刻）").click();

    await page.getByRole("button", { name: "平日" }).first().click();

    const entrySelect = page.locator("select").first();
    await entrySelect.selectOption("21:30");
    const exitSelect = page.locator("select").nth(1);
    await exitSelect.selectOption("23:30");

    // 手計算: 3 units @¥650 (21:30-22:00) + 9 units @¥715 (22:00-23:30) = 1950 + 6435 = ¥8,385
    // 加算しない旧仕様なら 12*650=¥7,800 になるはずで、¥8,385 が出れば加算が反映されている証拠。
    await expect(page.getByText("男性 合計（目安・相席時間ぶん）").locator("..").getByText("¥8,385")).toBeVisible();
    // 内訳表に深夜加算行が出る
    await expect(page.getByText(/相席（22:00以降・深夜10%加算）/)).toBeVisible();
  });

  test("renders an aisekiya card on a second store /store/ay_chiba (22:00 jump line present)", async ({
    page,
  }) => {
    await page.goto("/store/ay_chiba");
    await expect(page.getByText("料金の目安")).toBeVisible();
    await expect(page.getByText(/高料金の対象: 金・土・日曜日・祝日・祝前日/)).toBeVisible();
    // 平日¥715/週末¥825（曜日タイプは自動判定＝実行日に依存するため両方を許容する。詳細は
    // 上の ay_shibuya テストのコメント参照）。
    await expect(page.getByText(/22:00以降は相席 10分 ¥(715|825)/)).toBeVisible();
  });
});
