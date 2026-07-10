"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import MeguribiDashboardPreview from "../../../components/MeguribiDashboardPreview";
import {
  isFavoriteStore,
  recordStoreVisit,
  toggleFavoriteStore,
} from "@/lib/browser/meguribiStorage";
import { sendEvent } from "@/lib/analytics";
import {
  STORE_CARD_RANGE_LIMIT,
  STORE_CARD_SPARKLINE_POINTS,
  buildActualSparklineFromRange,
  buildGenderSparklineFromRange,
  parseRangeResponse,
  pickLatestRangeRow,
} from "@/lib/storeCardRangeSparkline";
import { ForecastAccuracyCard } from "@/components/ForecastAccuracyCard";
import { DEFAULT_STORE, STORES, STORE_REGION_FILTER_ORDER, distanceKm, getStoreMetaBySlug, getStoreMetaBySlugStrict } from "../../config/stores";
import type { StoreSnapshot } from "../../hooks/useStorePreviewData";
import { useDeferredFetchGate } from "./useDeferredFetchGate";
import { StorePageFallback } from "./StorePageFallback";
import { StoreReportSummarySection } from "./StoreReportSummarySection";
import { RelatedStoresSection } from "./RelatedStoresSection";
import type {
  RelatedRealtimeMap,
  ReportSummaryData,
  ReportSummaryItem,
} from "./storePageTypes";

function StorePageInner({ initialSnapshot }: { initialSnapshot: StoreSnapshot | null }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const params = useParams();

  const slugRaw = (params as { id?: string | string[] }).id;
  const slugFromPath =
    typeof slugRaw === "string"
      ? slugRaw
      : Array.isArray(slugRaw)
        ? slugRaw[0]
        : "";

  // URLパスの店舗slugが不正な場合は店舗一覧へリダイレクト
  const strictMeta = getStoreMetaBySlugStrict(slugFromPath);
  useEffect(() => {
    if (slugFromPath && !strictMeta) {
      router.replace("/stores");
    }
  }, [slugFromPath, strictMeta, router]);

  const meta = getStoreMetaBySlug(slugFromPath || searchParams.get("store") || DEFAULT_STORE);
  const slug = meta.slug;

  // メインのグラフ用データ（range/forecast_today）は MeguribiDashboardPreview 配下の
  // useStorePreviewData が持つが、ここ（StorePageInner）からは loading state を直接
  // 観測できない。ただし initialSnapshot が存在する場合、useStorePreviewData は
  // 最初のレンダーから loading:false で即描画する（storePreviewSnapshot 側の既存仕様）ため、
  // 「initialSnapshot の有無」をメインデータ即時性の代理シグナルとして使える。
  // initialSnapshot が無いコールド店舗では、フォールバックタイマー（既定 2500ms）だけで
  // 非クリティカルな並列フェッチをゲートする。
  const mainReady = initialSnapshot !== null;
  const canFireDeferred = useDeferredFetchGate(mainReady);

  useEffect(() => {
    if (!slug) return;

    const current = searchParams.get("store");
    if (current === slug) return;

    const sp = new URLSearchParams(searchParams.toString());
    sp.set("store", slug);
    const qs = sp.toString();

    router.replace(qs ? `/store/${slug}?${qs}` : `/store/${slug}`, {
      scroll: false,
    });
  }, [router, searchParams, slug]);

  useEffect(() => {
    if (!slug) return;
    recordStoreVisit(slug);
    sendEvent("store_view", { store_slug: slug, store_label: meta.label });
  }, [slug, meta.label]);

  // おすすめ（ほかの店舗）は「今見ている店舗に地理的に近い」店を出す。
  // 実座標（stores.json の lat/lon）が全店に入ったので、ハバサイン距離で近い順に並べる。
  // 座標が欠けた店だけは地域（regionLabel）の並び順で近似し、距離が取れる店の後ろに置く。
  const digestStores = useMemo(() => {
    const order = STORE_REGION_FILTER_ORDER;
    const curIdx = order.indexOf(meta.regionLabel);
    const regionDist = (region: string): number => {
      const i = order.indexOf(region);
      return curIdx < 0 || i < 0 ? 99 : Math.abs(i - curIdx);
    };
    return STORES.filter((s) => s.slug !== slug)
      .map((s, i) => {
        const km = distanceKm(meta, s);
        const p = km != null ? km : 100000 + regionDist(s.regionLabel);
        return { s, i, p };
      })
      .sort((a, b) => (a.p !== b.p ? a.p - b.p : a.i - b.i))
      .slice(0, 4)
      .map((x) => x.s);
  }, [slug, meta.regionLabel, meta.lat, meta.lon]);

  const [reportSummary, setReportSummary] = useState<ReportSummaryData>({ weekly: null });

  // 非クリティカル: グラフ本体（range/forecast_today）を待たせないよう、メインデータの
  // 初回解決かフォールバックタイマーまで発火を遅らせる（コールド店舗のバックエンド輻輳回避）。
  useEffect(() => {
    if (!slug || !canFireDeferred) return;
    let active = true;
    fetch(`/api/reports/store-summary?store=${encodeURIComponent(slug)}`, { cache: "no-store" })
      .then((r) => r.json())
      .then((body: { ok?: boolean; weekly?: ReportSummaryItem }) => {
        if (!active) return;
        if (body.ok) {
          setReportSummary({ weekly: body.weekly ?? null });
        }
      })
      .catch(() => {/* サイレント */});
    return () => { active = false; };
  }, [slug, canFireDeferred]);

  const [favorite, setFavorite] = useState(false);
  const [relatedRealtime, setRelatedRealtime] = useState<RelatedRealtimeMap>({});
  const [relatedLoading, setRelatedLoading] = useState(false);

  useEffect(() => {
    setFavorite(isFavoriteStore(slug));
  }, [slug]);

  // 非クリティカル: 関連店舗カードはグラフより後に見える位置にあるため、メインデータの
  // 初回解決かフォールバックタイマーまで発火を遅らせる（コールド店舗のバックエンド輻輳回避）。
  useEffect(() => {
    if (!canFireDeferred) return;
    let mounted = true;

    (async () => {
      setRelatedLoading(true);
      try {
        // 関連店舗は range_multi で1リクエストに束ねる（forecast_todayはメイン店舗のみ）
        const slugsCsv = digestStores.map((s) => s.slug).join(",");
        const batchRes = await fetch(
          `/api/range_multi?stores=${encodeURIComponent(slugsCsv)}&limit=${STORE_CARD_RANGE_LIMIT}`,
        );
        const batchBody = batchRes.ok
          ? ((await batchRes.json()) as { ok?: boolean; by_slug?: Record<string, { rows?: unknown[] }> })
          : null;
        const bySlug = batchBody?.ok && batchBody.by_slug ? batchBody.by_slug : null;

        const mapped: RelatedRealtimeMap = {};
        for (const store of digestStores) {
          try {
            const rows = bySlug?.[store.slug]?.rows ?? [];
            const rangeRows = parseRangeResponse({ rows });
            const current = pickLatestRangeRow(rangeRows) ?? {};
            const menNow = Math.max(0, Math.round(Number(current.men ?? 0)));
            const womenNow = Math.max(0, Math.round(Number(current.women ?? 0)));
            const nowTotal = Math.max(0, Math.round(Number(current.total ?? menNow + womenNow)));
            const genderSparks = buildGenderSparklineFromRange(rangeRows, STORE_CARD_SPARKLINE_POINTS);
            const actualTotals = buildActualSparklineFromRange(rangeRows, STORE_CARD_SPARKLINE_POINTS);
            mapped[store.slug] = {
              stats: {
                menCount: menNow,
                womenCount: womenNow,
                nowTotal,
                peakPredTotal: 0,
                genderRatio: `${menNow}:${womenNow}`,
                crowdLevel: undefined,
                recommendLabel: undefined,
              },
              sparkline: actualTotals,
              sparklineMen: genderSparks.men,
              sparklineWomen: genderSparks.women,
            };
          } catch {
            // 個別店舗の処理失敗は無視して続行
          }
        }

        if (!mounted) return;
        setRelatedRealtime(mapped);
      } catch {
        // サイレント
      }
      if (mounted) setRelatedLoading(false);
    })();

    return () => {
      mounted = false;
    };
  }, [digestStores, canFireDeferred]);

  const favoriteButton = (
    <button
      type="button"
      onClick={() => {
        const next = toggleFavoriteStore(slug);
        setFavorite(next);
        sendEvent(next ? "favorite_add" : "favorite_remove", { store_slug: slug });
      }}
      className="rounded-full border border-amber-400/35 bg-amber-500/10 px-3 py-1.5 text-xs font-medium text-amber-100 transition hover:border-amber-300/60 hover:bg-amber-500/20"
      aria-pressed={favorite}
      aria-label={favorite ? "お気に入りから外す" : "お気に入りに追加"}
    >
      {favorite ? "★ お気に入り済み" : "☆ お気に入りに追加"}
    </button>
  );

  // Daily Report は「今日の傾向まとめ」カードと内容が重複するため、このページでは Weekly のみ表示する
  const hasWeeklyReport = Boolean(reportSummary.weekly);

  return (
    <div className="space-y-8">
      <MeguribiDashboardPreview headerActions={favoriteButton} initialSnapshot={initialSnapshot} pathSlug={slug} />

      {/* AI レポート要約セクション（Weekly Report のみ） */}
      {hasWeeklyReport && (
        <StoreReportSummarySection weekly={reportSummary.weekly} slug={slug} />
      )}

      {/* 非クリティカル: モジュールレベルで長期キャッシュ済みだが、コールド店舗での
          初回輻輳を避けるため他の付随フェッチと同じゲートで遅らせる（trivial な変更）。 */}
      {canFireDeferred && (
        <section className="mx-auto w-full max-w-6xl px-4">
          <div className="max-w-xs">
            <ForecastAccuracyCard storeSlug={slug} brand={meta.brand} capacity={meta.capacity} />
          </div>
        </section>
      )}

      <RelatedStoresSection
        digestStores={digestStores}
        relatedRealtime={relatedRealtime}
        relatedLoading={relatedLoading}
      />
    </div>
  );
}

type StorePageClientProps = {
  /**
   * サーバー（page.tsx）で取得済みの初回スナップショット。today モード・現在の店舗と
   * 一致する場合のみ useStorePreviewData 側で採用され、グラフ/数値がハイドレーション直後に
   * 即座に表示される。取得失敗/タイムアウト時は null（=今まで通りの CSR フォールバック）。
   */
  initialSnapshot?: StoreSnapshot | null;
};

export default function StorePageClient({ initialSnapshot = null }: StorePageClientProps) {
  return (
    <Suspense fallback={<StorePageFallback />}>
      <StorePageInner initialSnapshot={initialSnapshot} />
    </Suspense>
  );
}
