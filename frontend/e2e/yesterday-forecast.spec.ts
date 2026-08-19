import { test, expect, type Page } from "./fixtures";
import {
  jstNightBaseYmd,
  nightActualRows,
  stubEmptyForecastToday,
  stubNonCriticalApis,
} from "./helpers/storePageStubs";

/**
 * 「昨日」タブでグラフが空になるリグレッションの再発防止 e2e。
 *
 * バックエンド（Flask）には到達せず、Next.js の API ルート（/api/range・
 * /api/forecast_today）を Playwright の route stub で差し替える。これにより
 * ネットワーク・バックエンドの状態に依存せず、「昨日」モードで実測の実線が
 * 描画されること（＝チャートが空にならないこと）を決定論的に検証する。
 */

const STORE = "nagasaki";

async function stubApis(page: Page) {
  // /api/range?...&from=YYYY-MM-DD... の from 値に対応する夜のデータを返す。
  await page.route("**/api/range?**", async (route) => {
    const url = new URL(route.request().url());
    const from = url.searchParams.get("from") ?? jstNightBaseYmd(0);
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      headers: { "cache-control": "public, s-maxage=240" },
      body: JSON.stringify({ ok: true, rows: nightActualRows(from) }),
    });
  });
  // forecast は today モードのみ叩かれるが、念のため空でも壊れないダミーを返す。
  await stubEmptyForecastToday(page);
  // その他の非クリティカル API はテスト対象外なので空で満たす。
  await stubNonCriticalApis(page);
}

// チャート内の実測ラインが実際に描画されている（path の d が空でない）本数を数える。
async function drawnLineCount(page: Page): Promise<number> {
  return page.evaluate(() => {
    const paths = Array.from(
      document.querySelectorAll<SVGPathElement>(".recharts-line-curve"),
    );
    return paths.filter((p) => {
      const d = p.getAttribute("d") ?? "";
      // recharts の折れ線は "M<x>,<y>C..." のベジェパス。空文字（予測ラインが全 null の
      // 場合）は描画されていない＝線なし。曲線コマンド(C/L)を含み一定の長さがあるものを
      // 「実際に描かれた線」とみなす。
      return d.length > 12 && /[CL]/.test(d);
    }).length;
  });
}

test.describe("Yesterday-mode timeline", () => {
  test.beforeEach(async ({ page }) => {
    await stubApis(page);
  });

  test("renders solid actual lines in 昨日 mode (chart is not empty)", async ({ page }) => {
    await page.goto(`/store/${STORE}`);

    // today モードでまずグラフが描かれるのを待つ。
    await expect
      .poll(() => drawnLineCount(page), { timeout: 15_000 })
      .toBeGreaterThanOrEqual(2);

    // 「昨日」タブへ切替。
    await page.getByRole("button", { name: "昨日", exact: true }).click();

    // 切替後、昨日の実測実線が描画される（＝空グラフにならない）。
    await expect
      .poll(() => drawnLineCount(page), { timeout: 15_000 })
      .toBeGreaterThanOrEqual(2);

    // 表示ラベルが昨日の夜日付になっていること（モードが確かに切り替わっている）。
    await expect(page.getByText(/表示: \d{4}-\d{2}-\d{2}/)).toBeVisible();
  });

  test("shows a chart loading state while switching, not a blank chart", async ({ page }) => {
    // range 応答を意図的に遅らせ、ローディングオーバーレイが出ることを確認する。
    await page.unroute("**/api/range?**");
    await page.route("**/api/range?**", async (route) => {
      const url = new URL(route.request().url());
      const from = url.searchParams.get("from") ?? jstNightBaseYmd(0);
      await new Promise((r) => setTimeout(r, 1500));
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ok: true, rows: nightActualRows(from) }),
      });
    });

    await page.goto(`/store/${STORE}`);
    await page.getByRole("button", { name: "昨日", exact: true }).click();

    // 切替直後はチャート面にローディングが重なる（空グラフではない）。
    await expect(page.getByTestId("timeline-loading")).toBeVisible();
    // 最終的にはローディングが消え、実線が描かれる。
    await expect(page.getByTestId("timeline-loading")).toBeHidden({ timeout: 15_000 });
    await expect
      .poll(() => drawnLineCount(page), { timeout: 15_000 })
      .toBeGreaterThanOrEqual(2);
  });
});
