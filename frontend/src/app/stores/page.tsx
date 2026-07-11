import { Suspense } from "react";
import type { Metadata } from "next";
import Link from "next/link";
import StoresListClient, { type StoreRealtimeCard } from "./stores-list-client";
import { STORES, buildStoreFullName } from "@/app/config/stores";
import { AREAS } from "@/app/config/areas";
import { fetchBackendSnapshot } from "@/lib/serverSnapshot";
import { getMetadataBaseUrl } from "@/lib/siteUrl";
import { buildBreadcrumbList, serializeJsonLd } from "@/lib/jsonLd";
import { SHOW_MEGRIBI_JUDGMENTS } from "@/lib/featureFlags";
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

const base = getMetadataBaseUrl();

export const metadata: Metadata = {
  alternates: { canonical: new URL("/stores", base).href },
};

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
    // 判定表示OFF中はスコアバッジ自体が非表示のため取得をスキップ
    // （featureFlags.ts の SHOW_MEGRIBI_JUDGMENTS を true に戻せば自動復活）。
    SHOW_MEGRIBI_JUDGMENTS
      ? fetchBackendSnapshot<MegribiScoreResponse>(
          `/api/megribi_score?stores=${encodeURIComponent(slugsCsv)}`,
          120,
        )
      : Promise.resolve(null),
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

/**
 * /store/{slug} への実アンカーを raw HTML に載せるための SSR ナビブロック。
 * StoresListClient はカードをクライアント側 fetch 完了後に描画するため、フィルタ無しの
 * 初回 HTML には <a href="/store/..."> が1つも出ない（クローラーが読む raw HTML に内部リンクが
 * 無い状態になる）。ここで全店舗（登録済み・新潟等の閉店店舗は STORES に含まれない）を
 * サーバー側で列挙し、地域ごとに実アンカーとして出力する。クライアント側のフィルタ/検索UIとは
 * 独立した別ブロックなので、CSR の絞り込みロジックには一切触れない。
 */
/**
 * 大阪・名古屋・渋谷・上野・横浜など、複数店舗が集まるエリアのハブページ（/area/{id}）への
 * 導線。エリアページは店舗ページ側から到達できるが、一覧ページからも張っておくことで
 * 孤立ページ化を防ぐ（SEO Phase2の内部リンク方針と同じ考え方）。
 */
function AreaHubsSsrNav() {
  if (AREAS.length === 0) return null;
  return (
    <section aria-labelledby="area-hubs-heading" className="border-t border-white/10 pb-8 pt-6">
      <h2 id="area-hubs-heading" className="text-sm font-semibold text-white/70">
        エリア特集
      </h2>
      <p className="mt-1 text-[11px] text-white/40">
        複数店舗が集まるエリアは、まとめて混雑状況を比較できるページも用意しています。
      </p>
      <ul className="mt-3 flex flex-wrap gap-x-3 gap-y-1.5">
        {AREAS.map((area) => (
          <li key={area.id}>
            <Link
              href={`/area/${area.id}`}
              className="text-xs text-white/60 underline decoration-white/20 underline-offset-2 transition hover:text-indigo-200 hover:decoration-indigo-300"
            >
              {area.displayName}の相席ラウンジ一覧 →
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

function AllStoresSsrNav() {
  const byRegion = new Map<string, typeof STORES>();
  for (const store of STORES) {
    const list = byRegion.get(store.regionLabel);
    if (list) list.push(store);
    else byRegion.set(store.regionLabel, [store]);
  }

  return (
    <section aria-labelledby="all-stores-heading" className="border-t border-white/10 pb-10 pt-6">
      <h2 id="all-stores-heading" className="text-sm font-semibold text-white/70">
        全店舗一覧
      </h2>
      <p className="mt-1 text-[11px] text-white/40">
        地域ごとの全{STORES.length}店舗です。店舗名をタップすると混雑状況ページへ移動します。
      </p>
      <nav aria-label="全店舗一覧" className="mt-3 space-y-4">
        {[...byRegion.entries()].map(([region, stores]) => (
          <div key={region}>
            <p className="text-[11px] font-medium text-white/45">{region}</p>
            <ul className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1.5">
              {stores.map((store) => (
                <li key={store.slug}>
                  <Link
                    href={`/store/${store.slug}`}
                    className="text-xs text-white/60 underline decoration-white/20 underline-offset-2 transition hover:text-indigo-200 hover:decoration-indigo-300"
                  >
                    {buildStoreFullName(store)}（{store.areaLabel}）
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>
    </section>
  );
}

export default async function StoresPage() {
  const initialCards = await fetchInitialStoreCards();

  const breadcrumbJsonLd = serializeJsonLd(
    buildBreadcrumbList([
      { name: "ホーム", item: base.href.replace(/\/+$/, "") || base.href },
      { name: "店舗一覧", item: new URL("/stores", base).href },
    ]),
  );

  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: breadcrumbJsonLd }} />
      <Suspense fallback={<StoresFallback />}>
        <StoresListClient initialCards={initialCards} />
      </Suspense>
      <div className="relative z-10 flex justify-center bg-[#050505]">
        <div className="w-full max-w-[1080px] px-4">
          <AreaHubsSsrNav />
          <AllStoresSsrNav />
        </div>
      </div>
    </>
  );
}
