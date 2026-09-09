// frontend/src/lib/reports/reportAvailability.ts
//
// 「記事が本当に存在しない」と「一時的に取得できていない」を分ける判定の単一ソース。
//
// なぜ必要か（2026-09-09・Supabase 402 事故）:
//   /reports/daily/[store_slug] と /reports/weekly/[store_slug] は行が取れないと
//   一律 notFound() を呼んでいた。Supabase が全リクエストに 402 を返した 3 日半、
//   実在する 84 本のレポート URL が 404 を返し続け、その 404 が CDN に HIT で載って
//   復旧後もしばらく残り、Search Console にクロールエラーが積み上がった。
//   取得できていないだけなら 404 にしない（＝消えた扱いにしない）。

/** fetchLatestPublishedReportByStoreWithStatus の戻り値の形。 */
export type ReportFetchResult<T> = { row: T | null; failed: boolean };

export type ReportAvailability<T> =
  | { state: "found"; row: T }
  /** 障害・設定不備で見に行けていない。404 ではなく「一時的に取得できません」を返す。 */
  | { state: "temporarily-unavailable" }
  /** 取得はできたうえで 0 件＝そのレポートは本当に存在しない。ここだけ 404。 */
  | { state: "not-found" };

export function decideReportAvailability<T>(
  result: ReportFetchResult<T>,
): ReportAvailability<T> {
  if (result.row) return { state: "found", row: result.row };
  return result.failed ? { state: "temporarily-unavailable" } : { state: "not-found" };
}
