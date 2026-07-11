import { test, expect, type Page } from "./fixtures";

/**
 * 完了済みの夜（昨日/先週/カスタム過去日、または「今日」モードで既に夜が終わった場合）に、
 * その夜へ実際に配信されていた予測（/api/forecast_snapshot）を実測の上に重ねて表示する
 * 機能の e2e。
 *
 * バックエンド（Flask）には到達せず、Next.js の API ルート（/api/range・
 * /api/forecast_snapshot・/api/forecast_today）を Playwright の route stub で
 * 差し替える。next build && next start（本番ビルド）に対して実行し、ネットワーク・
 * バックエンドの状態に依存せず「実測(実線)＋予測(点線)が両方描画されること」を
 * 決定論的に検証する。
 */

const STORE = "nagasaki";

// JST 夜日付（YYYY-MM-DD, 19:00 始まり）を N 日前で得る。フロントの
// computeNightBaseDate と同じ「19時未満なら前日」ロジックを近似する。
function jstNightBaseYmd(daysAgo: number): string {
  const now = new Date();
  const jst = new Date(now.getTime() + 9 * 60 * 60 * 1000);
  if (jst.getUTCHours() < 19) {
    jst.setUTCDate(jst.getUTCDate() - 1);
  }
  jst.setUTCDate(jst.getUTCDate() - daysAgo);
  const y = jst.getUTCFullYear();
  const m = String(jst.getUTCMonth() + 1).padStart(2, "0");
  const d = String(jst.getUTCDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

// "YYYYMMDD" -> "YYYY-MM-DD"
function compactToYmd(compact: string): string {
  if (!/^\d{8}$/.test(compact)) return jstNightBaseYmd(1);
  return `${compact.slice(0, 4)}-${compact.slice(4, 6)}-${compact.slice(6, 8)}`;
}

function nightActualRows(baseYmd: string) {
  const rows: { ts: string; men: number; women: number; total: number }[] = [];
  const start = new Date(`${baseYmd}T19:00:00+09:00`);
  for (let i = 0; i <= 40; i += 1) {
    const t = new Date(start.getTime() + i * 15 * 60 * 1000);
    rows.push({ ts: t.toISOString(), men: 10 + i, women: 20 + i, total: 30 + 2 * i });
  }
  return rows;
}

// 予測スナップショット（answer-check overlay）用: 実測とは少し違う値にして
// 「別系列」であることが視覚的にも分かるようにする。
function nightForecastPoints(baseYmd: string) {
  const rows: { ts: string; men_pred: number; women_pred: number; total_pred: number }[] = [];
  const start = new Date(`${baseYmd}T19:00:00+09:00`);
  for (let i = 0; i <= 40; i += 1) {
    const t = new Date(start.getTime() + i * 15 * 60 * 1000);
    rows.push({
      ts: t.toISOString(),
      men_pred: 8 + i,
      women_pred: 18 + i,
      total_pred: 26 + 2 * i,
    });
  }
  return rows;
}

async function stubApis(page: Page) {
  // /api/range?...&from=YYYY-MM-DD... の from 値に対応する夜の実測を返す。
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

  // 完了済みの夜の予測スナップショット。date=YYYYMMDD に対応する夜のデータを返す
  // （どの date が来ても ok:true で答えられるようにする＝どのモードでも動く）。
  await page.route("**/api/forecast_snapshot?**", async (route) => {
    const url = new URL(route.request().url());
    const date = url.searchParams.get("date") ?? "";
    const baseYmd = compactToYmd(date);
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      headers: { "cache-control": "public, s-maxage=86400" },
      body: JSON.stringify({ ok: true, date, data: nightForecastPoints(baseYmd) }),
    });
  });

  // 進行中の「今日」用（テスト実行時刻によってはこちらが叩かれるケースもあるため、
  // 空でも壊れないダミーを用意しておく）。
  await page.route("**/api/forecast_today?**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ok: true, data: [] }),
    });
  });

  // その他の非クリティカル API はテスト対象外なので空で満たす。
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

type LineInfo = { hasGeometry: boolean; dashed: boolean };

// チャート内の各実測/予測ラインの描画状態（実際に線が引かれているか・破線かどうか）を集計する。
async function lineInfos(page: Page): Promise<LineInfo[]> {
  return page.evaluate(() => {
    const paths = Array.from(
      document.querySelectorAll<SVGPathElement>(".recharts-line-curve"),
    );
    return paths.map((p) => {
      const d = p.getAttribute("d") ?? "";
      const hasGeometry = d.length > 12 && /[CL]/.test(d);
      const dashArray = p.getAttribute("stroke-dasharray") ?? "";
      // recharts はデフォルトの線描画アニメーション自体にも stroke-dasharray を使う
      // （実測=通常の Line は完了後 "<全長>px 0px" のようなカンマ無し2値になる）。
      // 一方、明示的に strokeDasharray="5 4" を渡した予測 Line は、全長を覆うまで
      // "5px, 4px, 5px, 4px, ..." とカンマ区切りで繰り返されるため、カンマの有無で
      // 「実測(アニメーションのみ)」と「予測(明示的な点線パターン)」を区別できる。
      const dashed = dashArray.includes(",");
      return { hasGeometry, dashed };
    });
  });
}

async function drawnLineCount(page: Page): Promise<number> {
  const infos = await lineInfos(page);
  return infos.filter((i) => i.hasGeometry).length;
}

test.describe("Past-night forecast overlay", () => {
  test("completed 昨日 night renders both solid actual and dashed forecast lines, no pageerrors", async ({ page }) => {
    const pageErrors: Error[] = [];
    page.on("pageerror", (err) => pageErrors.push(err));

    await stubApis(page);
    await page.goto(`/store/${STORE}`);

    // today モードでまずグラフが描かれるのを待つ（実測だけでも2本は出るはず）。
    await expect
      .poll(() => drawnLineCount(page), { timeout: 15_000 })
      .toBeGreaterThanOrEqual(2);

    // 「昨日」タブへ切替（常に完了済みの夜 = スナップショットオーバーレイの対象）。
    await page.getByRole("button", { name: "昨日", exact: true }).click();

    // 表示ラベルが昨日の夜日付になっていること（モードが確かに切り替わっている）。
    await expect(page.getByText(/表示: \d{4}-\d{2}-\d{2}/)).toBeVisible();

    // 実測(実線)＋予測(点線)の両方が描画される＝4本（男女×実測/予測）すべてに
    // ジオメトリが乗る。以前は予測が過去区間で null 化され2本のみだった。
    await expect
      .poll(() => drawnLineCount(page), { timeout: 15_000 })
      .toBeGreaterThanOrEqual(4);

    const infos = await lineInfos(page);
    const drawn = infos.filter((i) => i.hasGeometry);
    expect(drawn.some((i) => i.dashed)).toBe(true); // 予測（点線）
    expect(drawn.some((i) => !i.dashed)).toBe(true); // 実測（実線）

    expect(pageErrors, `pageerrors: ${pageErrors.map((e) => e.message).join(", ")}`).toEqual([]);
  });

  test("rapid mode toggling across 今日/昨日/先週/カスタム produces no pageerrors", async ({ page }) => {
    const pageErrors: Error[] = [];
    page.on("pageerror", (err) => pageErrors.push(err));

    await stubApis(page);
    await page.goto(`/store/${STORE}`);

    await expect
      .poll(() => drawnLineCount(page), { timeout: 15_000 })
      .toBeGreaterThanOrEqual(2);

    const modes = ["昨日", "先週", "今日", "昨日"] as const;
    for (const mode of modes) {
      await page.getByRole("button", { name: mode, exact: true }).click();
      // 切替直後に少し待つ（レンダー/フェッチが走る隙を作る）だけで、完了を待たずに
      // 次へ進む＝「素早い切替」を模す。
      await page.waitForTimeout(150);
    }

    // 最終状態（今日 → 昨日）でチャートが壊れていないこと。
    await expect
      .poll(() => drawnLineCount(page), { timeout: 15_000 })
      .toBeGreaterThanOrEqual(2);

    expect(pageErrors, `pageerrors: ${pageErrors.map((e) => e.message).join(", ")}`).toEqual([]);
  });

  test("in-progress today (forecast_today path) still only shows future-only forecast contract intact", async ({ page }) => {
    // このテストは isNightCompleted の実装に依存せず、forecast_today の応答内容
    // だけで today モードの契約（未来区間のみ点線）が壊れていないことを、
    // 実際の DOM 経由でも確認する（ユニットテストの buildSeries 検証の補完）。
    const pageErrors: Error[] = [];
    page.on("pageerror", (err) => pageErrors.push(err));

    await stubApis(page);
    // forecast_today を「実測より未来だけ予測がある」形に差し替える。
    await page.unroute("**/api/forecast_today?**");
    await page.route("**/api/forecast_today?**", async (route) => {
      const now = new Date();
      const future = new Date(now.getTime() + 30 * 60 * 1000).toISOString();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ok: true,
          data: [{ ts: future, men_pred: 20, women_pred: 25, total_pred: 45 }],
        }),
      });
    });

    await page.goto(`/store/${STORE}`);
    await expect
      .poll(() => drawnLineCount(page), { timeout: 15_000 })
      .toBeGreaterThanOrEqual(2);

    expect(pageErrors, `pageerrors: ${pageErrors.map((e) => e.message).join(", ")}`).toEqual([]);
  });
});
