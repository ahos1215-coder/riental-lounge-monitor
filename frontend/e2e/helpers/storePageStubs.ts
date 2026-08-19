import type { Page } from "../fixtures";

/**
 * 店舗ページ e2e の共通スタブ。
 *
 * 「夜日付の作り方」と「テスト対象外 API の空応答」が spec ごとにコピーされていたため
 * ここへ集約した。夜窓の境界（19時始まり）を変える時に spec の直し漏れが起きないようにする。
 */

/**
 * JST 夜日付（YYYY-MM-DD, 19:00 始まり）を N 日前で得る。
 * フロントの computeNightBaseDate と同じ「19時未満なら前日」ロジックを近似する。
 */
export function jstNightBaseYmd(daysAgo: number): string {
  const now = new Date();
  const jst = new Date(now.getTime() + 9 * 60 * 60 * 1000);
  // 19時未満なら夜日付は前日
  if (jst.getUTCHours() < 19) {
    jst.setUTCDate(jst.getUTCDate() - 1);
  }
  jst.setUTCDate(jst.getUTCDate() - daysAgo);
  const y = jst.getUTCFullYear();
  const m = String(jst.getUTCMonth() + 1).padStart(2, "0");
  const d = String(jst.getUTCDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

/** 指定した夜（19:00 JST 始まり・15分刻み41点）の実測行。 */
export function nightActualRows(baseYmd: string) {
  const rows: { ts: string; men: number; women: number; total: number }[] = [];
  const start = new Date(`${baseYmd}T19:00:00+09:00`);
  for (let i = 0; i <= 40; i += 1) {
    const t = new Date(start.getTime() + i * 15 * 60 * 1000);
    rows.push({ ts: t.toISOString(), men: 10 + i, women: 20 + i, total: 30 + 2 * i });
  }
  return rows;
}

/** /api/forecast_today を「予測なし」で固定する（today モードが叩いても壊れないダミー）。 */
export async function stubEmptyForecastToday(page: Page): Promise<void> {
  await page.route("**/api/forecast_today?**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ok: true, data: [] }),
    });
  });
}

/** テスト対象外の API（週報カード・一覧・精度カード）を空応答で満たす。 */
export async function stubNonCriticalApis(page: Page): Promise<void> {
  await page.route("**/api/reports/store-summary?**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, weekly: null }) }),
  );
  await page.route("**/api/range_multi?**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, by_slug: {} }) }),
  );
  await page.route("**/api/forecast_accuracy?**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true }) }),
  );
}
