import type { Page } from "../fixtures";
import { addDays, computeNightBaseDate, formatYMD } from "@/lib/date/nightWindow";

/**
 * 店舗ページ e2e の共通スタブ。
 *
 * 「夜日付の作り方」と「テスト対象外 API の空応答」が spec ごとにコピーされていたため
 * ここへ集約した。夜窓の境界（19時始まり）を変える時に spec の直し漏れが起きないようにする。
 */

/**
 * JST 夜日付（YYYY-MM-DD, 19:00 始まり）を N 日前で得る。
 * 以前は「+9h して UTC の時/日を読む」近似実装だったが、境界時刻でアプリ本体と
 * ずれ得たため、本体と同じ lib/date/nightWindow の関数をそのまま使う。
 */
export function jstNightBaseYmd(daysAgo: number): string {
  return formatYMD(addDays(computeNightBaseDate(new Date()), -daysAgo));
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
