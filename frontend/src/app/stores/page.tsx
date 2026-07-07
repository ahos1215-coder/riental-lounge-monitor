import { Suspense } from "react";
import StoresListClient, { type StoreRealtimeCard } from "./stores-list-client";
import { STORES } from "@/app/config/stores";
import { fetchBackendSnapshot } from "@/lib/serverSnapshot";
import {
  STORE_CARD_RANGE_LIMIT,
  STORE_CARD_SPARKLINE_POINTS,
  buildActualSparklineFromRange,
  buildGenderSparklineFromRange,
  parseRangeResponse,
  pickLatestRangeRow,
} from "@/lib/storeCardRangeSparkline";

/** /api/range_multi のCDN TTL(60s)に合わせる。一覧1ページ目の初期表示はこの粒度で十分。 */
export const revalidate = 60;

/** デフォルト表示（フィルタ無し・1ページ目）の店舗数と一致させる。 */
const INITIAL_PAGE_SIZE = 12;

type RangeMultiResponse = {
  ok?: boolean;
  by_slug?: Record<string, { rows?: unknown[] }>;
};

type MegribiScoreResponse = {
  ok?: boolean;
  data?: { slug: string; score?: number }[];
};

function StoresFallback() {
  return (
    <div className="flex min-h-[60vh] w-full items-center justify-center bg-[#050505] font-display text-sm text-white/50">
      読み込み中…
    </div>
  );
}

/**
 * /stores 1ページ目（フィルタ無し・先頭12店舗）分の range_multi + megribi_score を
 * サーバー側で先取りし、クライアント側が range 到着直後に出す“部分カード”と同じ形に
 * 組み立てる。forecast（crowdLevel/recommendLabel/peakPredTotal）は含めない：
 * - forecast_today_multi はバックエンド側で最大 ~7秒かかることがあり、SSR で待つと
 *   ページの初期表示そのものが遅くなり本末転倒になるため。
 * - クライアント側は元々「range 到着→forecast 後追い」の2段階描画をしており、
 *   ここではその1段階目（部分カード）をサーバーで先にやるだけ。forecastPending:true を
 *   立てておけば見た目は今まで通り「取得中」から始まり、クライアント fetch が追いついて
 *   forecast を埋める。
 *
 * COLD SAFETY: fetchBackendSnapshot は失敗・タイムアウトで null を返すだけなので、
 * ここも失敗時は null を返し、StoresListClient は initialCards 無しの従来動作
 * （空のスケルトンからクライアント fetch）にフォールバックする。
 */
async function fetchInitialStoreCards(): Promise<Record<string, StoreRealtimeCard> | null> {
  const targets = STORES.slice(0, INITIAL_PAGE_SIZE);
  if (targets.length === 0) return null;
  const slugsCsv = targets.map((s) => s.slug).join(",");

  const [rangeJson, scoreJson] = await Promise.all([
    fetchBackendSnapshot<RangeMultiResponse>(
      `/api/range_multi?stores=${encodeURIComponent(slugsCsv)}&limit=${STORE_CARD_RANGE_LIMIT}`,
      60,
    ),
    fetchBackendSnapshot<MegribiScoreResponse>(
      `/api/megribi_score?stores=${encodeURIComponent(slugsCsv)}`,
      120,
    ),
  ]);

  // range が取れなければカードの土台が作れないため snapshot 自体を諦める
  // （megribi_score だけ取れなくてもスコアバッジが無いだけで致命的ではないので許容する）。
  if (!rangeJson?.ok || !rangeJson.by_slug) return null;

  const scoreMap = new Map<string, number>();
  if (Array.isArray(scoreJson?.data)) {
    for (const d of scoreJson.data) {
      if (d && typeof d.slug === "string" && typeof d.score === "number") {
        scoreMap.set(d.slug, d.score);
      }
    }
  }

  const cards: Record<string, StoreRealtimeCard> = {};
  for (const store of targets) {
    const rows = rangeJson.by_slug[store.slug]?.rows;
    if (!Array.isArray(rows)) continue;

    const rangeRows = parseRangeResponse({ rows });
    const actualSparkline = buildActualSparklineFromRange(rangeRows, STORE_CARD_SPARKLINE_POINTS);
    const { men: sparklineMen, women: sparklineWomen } = buildGenderSparklineFromRange(
      rangeRows,
      STORE_CARD_SPARKLINE_POINTS,
    );
    const current = pickLatestRangeRow(rangeRows) ?? {};
    const menNow = Math.max(0, Math.round(Number(current.men ?? 0)));
    const womenNow = Math.max(0, Math.round(Number(current.women ?? 0)));
    const nowTotal = Math.max(0, Math.round(Number(current.total ?? menNow + womenNow)));

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
      megribiScore: scoreMap.has(store.slug) ? (scoreMap.get(store.slug) as number) : null,
    };
  }

  return Object.keys(cards).length > 0 ? cards : null;
}

export default async function StoresPage() {
  const initialCards = await fetchInitialStoreCards();

  return (
    <Suspense fallback={<StoresFallback />}>
      <StoresListClient initialCards={initialCards} />
    </Suspense>
  );
}
