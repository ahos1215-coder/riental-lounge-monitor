/**
 * その瞬間が属する「週」を JST（Asia/Tokyo）基準の月曜始まりで求め、`YYYY年M月D日週` を返す。
 *
 * 従来は `new Date()` の getDay/getDate（サーバーの実行環境=UTC 基準）で月曜を算出していたため、
 * 毎週月曜 00:00〜08:59 JST（= 日曜 15:00〜23:59 UTC）の約9時間だけ前週の日付を表示していた。
 * ここでは Intl で JST の壁時計（年月日・曜日）を取り出してから月曜へ巻き戻すことで、
 * 日次側（timeZone: "Asia/Tokyo"）と表示基準を一致させる。純関数のためユニットテスト可能。
 */
export function jstWeekLabel(now: Date = new Date()): string {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Tokyo",
    year: "numeric",
    month: "numeric",
    day: "numeric",
    weekday: "short",
  }).formatToParts(now);
  const pick = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  const year = Number(pick("year"));
  const month = Number(pick("month"));
  const day = Number(pick("day"));
  const weekdayIndex: Record<string, number> = {
    Sun: 0,
    Mon: 1,
    Tue: 2,
    Wed: 3,
    Thu: 4,
    Fri: 5,
    Sat: 6,
  };
  const dow = weekdayIndex[pick("weekday")] ?? 0;
  // JST の壁時計を UTC 上に写像し、そのまま UTC 系の日付演算で月曜へ巻き戻す（TZ 二重変換を避ける）。
  const monday = new Date(Date.UTC(year, month - 1, day));
  monday.setUTCDate(monday.getUTCDate() - ((dow + 6) % 7));
  return `${monday.getUTCFullYear()}年${monday.getUTCMonth() + 1}月${monday.getUTCDate()}日週`;
}
