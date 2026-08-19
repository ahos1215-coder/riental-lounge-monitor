// frontend/src/lib/store/nightHourlyRollup.ts
//
// 「夜（19:00→翌05:00）の時間帯別ロールアップ」の単一ソース。
//
// 経緯: 店舗ページの SSR テキスト（ssrSummary）とエリアページ（areaLiveSummary）が
// 「同じ時の最大値を代表にする」「19→23→0→5 の夜順に並べる」「2時間分未満なら出さない」を
// それぞれ別実装で持ち、MIN_HOURLY_BUCKETS まで二重定義していた（両ファイルのヘッダーが
// 『厳守事項は同じ』と人手同期を宣言していた）。集計だけをここに寄せる。
//
// 文言（「約NN%」「NN人」等）は各ページで形が違う（スタットカード型 / 一文型）ため、
// **ここでは組み立てない**。時の抽出（ラベル正規表現 / ts の JST 時）も呼び出し側の責務。

/** 時間帯別サマリーを出すのに必要な最小の時間数（1点だけでは「推移」にならない） */
export const MIN_HOURLY_BUCKETS = 2;

export type NightHourBucket = {
  /** JST の「時」（0-23） */
  hour: number;
  /** その時間帯の代表値（最大値） */
  total: number;
};

/** 夜窓は 19:00→翌05:00 なので、19〜23 を 00〜05 より前に並べる（夜の流れ順）。 */
function nightOrder(hour: number): number {
  return hour >= 19 ? hour : hour + 24;
}

/**
 * 同じ「時」の点をまとめ、最大値をその時間帯の代表値にする。0 以下（人がいない）は捨てる。
 * 戻りは夜順（19→23→0→5）。
 */
export function rollUpByNightHour(
  points: readonly NightHourBucket[],
): NightHourBucket[] {
  const byHour = new Map<number, number>();
  for (const p of points) {
    if (p.total <= 0) continue;
    const prev = byHour.get(p.hour);
    if (prev === undefined || p.total > prev) byHour.set(p.hour, p.total);
  }
  return [...byHour.entries()]
    .sort((a, b) => nightOrder(a[0]) - nightOrder(b[0]))
    .map(([hour, total]) => ({ hour, total }));
}
