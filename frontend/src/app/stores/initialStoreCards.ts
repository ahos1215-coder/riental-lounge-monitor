// frontend/src/app/stores/initialStoreCards.ts
//
// /stores の SSR スナップショット（page.tsx）が range_multi のレスポンスからカードを
// 組み立てる部分。page.tsx はルートファイルで任意の export を足せない（Next のページ
// export 検証に引っかかる）ため、テストできるようここへ切り出している。

import {
  STORE_CARD_SPARKLINE_POINTS,
  buildActualSparklineFromRange,
  buildGenderSparklineFromRange,
} from "@/lib/storeCardRangeSparkline";
import { latestCountsOrZero, pickLatestRow } from "@/lib/range/rangeRows";
import { readRangeMultiSlug } from "@/lib/range/rangeMultiStatus";
import type { StoreRealtimeCard } from "./stores-list-client";

/** カード組み立てに必要な店舗情報だけを要求する（テストから最小の入力で呼べるように）。 */
export type InitialCardTarget = { slug: string };

/**
 * range_multi の by_slug と megribi_score から 1 ページ目ぶんのカードを作る。
 *
 * 取得できなかった店は **stats を付けず** dataUnavailable:true のカードにする。
 * 旧実装は `by_slug[slug]?.rows` が配列でありさえすれば（＝部分障害の `rows: []` でも）
 * カードを作っていたため、Supabase 402 の 3 日半、全店が「男性0 / 女性0 / 計0」に
 * 見えていた（2026-09-09）。0 人と欠測は別物として描く。
 */
export function buildInitialStoreCards(
  targets: InitialCardTarget[],
  bySlug: Record<string, unknown> | undefined,
  scoreMap: Map<string, number>,
): Record<string, StoreRealtimeCard> {
  const cards: Record<string, StoreRealtimeCard> = {};
  for (const store of targets) {
    const megribiScore = scoreMap.has(store.slug) ? (scoreMap.get(store.slug) as number) : null;
    const outcome = readRangeMultiSlug(bySlug?.[store.slug]);
    if (!outcome.available) {
      cards[store.slug] = {
        slug: store.slug,
        sparkline: [],
        sparklineMen: [],
        sparklineWomen: [],
        forecastPending: false,
        dataUnavailable: true,
        megribiScore,
      };
      continue;
    }

    const rangeRows = outcome.rows;
    const actualSparkline = buildActualSparklineFromRange(rangeRows, STORE_CARD_SPARKLINE_POINTS);
    const { men: sparklineMen, women: sparklineWomen } = buildGenderSparklineFromRange(
      rangeRows,
      STORE_CARD_SPARKLINE_POINTS,
    );
    const current = pickLatestRow(rangeRows) ?? {};
    const { men: menNow, women: womenNow, total: nowTotal } = latestCountsOrZero(current);

    cards[store.slug] = {
      slug: store.slug,
      stats: {
        menCount: menNow,
        womenCount: womenNow,
        nowTotal,
        peakPredTotal: 0,
        genderRatio: `${menNow}:${womenNow}`,
        crowdLevel: "取得中",
        recommendLabel: "取得中",
      },
      sparkline: actualSparkline,
      sparklineMen,
      sparklineWomen,
      forecastPending: true,
      megribiScore,
    };
  }
  return cards;
}
