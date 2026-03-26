"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { StoreCard } from "@/components/StoreCard";
import MeguribiDashboardPreview from "../../../components/MeguribiDashboardPreview";
import {
  isFavoriteStore,
  recordStoreVisit,
  toggleFavoriteStore,
} from "@/lib/browser/meguribiStorage";
import {
  STORE_CARD_RANGE_LIMIT,
  STORE_CARD_SPARKLINE_POINTS,
  buildActualSparklineFromRange,
  buildGenderSparklineFromRange,
  parseRangeResponse,
  pickLatestRangeRow,
} from "@/lib/storeCardRangeSparkline";
import { DEFAULT_STORE, STORES, getStoreMetaBySlug } from "../../config/stores";

type ForecastCardPoint = { ts: string; total_pred?: number };
type RealtimeCardStats = {
  menCount: number;
  womenCount: number;
  nowTotal: number;
  peakPredTotal: number;
  genderRatio: string;
  crowdLevel: string;
  recommendLabel: string;
};

function toHmJstStore(iso: string): string {
  return new Intl.DateTimeFormat("ja-JP", {
    timeZone: "Asia/Tokyo",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(iso));
}

function crowdLabelFromPredStore(maxPred: number): string {
  if (maxPred >= 120) return "混雑";
  if (maxPred >= 80) return "ほどよい";
  return "空いている";
}

function StorePageFallback() {
  return (
    <div className="mx-auto w-full max-w-6xl space-y-8 px-4 py-8">
      <div className="space-y-3">
        <div className="h-5 w-48 animate-pulse rounded bg-slate-700/80" />
        <div className="h-40 w-full animate-pulse rounded-2xl bg-slate-800/80" />
        <div className="h-72 w-full animate-pulse rounded-2xl bg-slate-800/80" />
      </div>
      <div className="space-y-3">
        <div className="h-4 w-40 animate-pulse rounded bg-slate-700/80" />
        <div className="grid gap-3 md:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <div
              key={i}
              className="h-44 animate-pulse rounded-2xl border border-slate-800/80 bg-slate-900/60"
            />
          ))}
        </div>
      </div>
    </div>
  );
}

function StorePageInner() {
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

  const meta = getStoreMetaBySlug(slugFromPath || searchParams.get("store") || DEFAULT_STORE);
  const slug = meta.slug;

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
  }, [slug]);

  const digestStores = useMemo(
    () => STORES.filter((s) => s.slug !== slug).slice(0, 4),
    [slug],
  );

  const [favorite, setFavorite] = useState(false);
  const [relatedRealtime, setRelatedRealtime] = useState<
    Record<
      string,
      {
        stats: RealtimeCardStats;
        sparkline: number[];
        sparklineMen: number[];
        sparklineWomen: number[];
      }
    >
  >({});
  const [relatedLoading, setRelatedLoading] = useState(false);

  useEffect(() => {
    setFavorite(isFavoriteStore(slug));
  }, [slug]);

  useEffect(() => {
    let mounted = true;

    (async () => {
      setRelatedLoading(true);
      const results = await Promise.all(
        digestStores.map(async (store) => {
          try {
            const [forecastRes, rangeRes] = await Promise.all([
              fetch(`/api/forecast_today?store=${encodeURIComponent(store.slug)}`, { cache: "no-store" }),
              fetch(
                `/api/range?store=${encodeURIComponent(store.slug)}&limit=${STORE_CARD_RANGE_LIMIT}`,
                { cache: "no-store" },
              ),
            ]);
            const forecastBody = (await forecastRes.json()) as { data?: ForecastCardPoint[] };
            const rangeBody: unknown = await rangeRes.json();
            const forecastRows = Array.isArray(forecastBody?.data) ? forecastBody.data : [];
            const rangeRows = parseRangeResponse(rangeBody);
            const current = pickLatestRangeRow(rangeRows) ?? {};
            const menNow = Math.max(0, Math.round(Number(current.men ?? 0)));
            const womenNow = Math.max(0, Math.round(Number(current.women ?? 0)));
            const nowTotal = Math.max(0, Math.round(Number(current.total ?? menNow + womenNow)));
            const totals = forecastRows
              .map((r) => Math.max(0, Math.round(Number(r.total_pred ?? 0))))
              .filter((n) => Number.isFinite(n));
            const maxPred = totals.length ? Math.round(Math.max(...totals)) : 0;
            let calm = forecastRows[0];
            for (const r of forecastRows) {
              if (Number(r.total_pred ?? 0) < Number(calm?.total_pred ?? Number.POSITIVE_INFINITY)) {
                calm = r;
              }
            }
            const calmLabel = calm?.ts ? toHmJstStore(calm.ts) : "--:--";
            const forecastSpark = totals.slice(0, 10);
            const genderSparks = buildGenderSparklineFromRange(rangeRows, STORE_CARD_SPARKLINE_POINTS);
            const actualTotals = buildActualSparklineFromRange(rangeRows, STORE_CARD_SPARKLINE_POINTS);
            const sparklineFallback =
              actualTotals.length >= 2 ? actualTotals : forecastSpark;
            return {
              slug: store.slug,
              stats: {
                menCount: menNow,
                womenCount: womenNow,
                nowTotal,
                peakPredTotal: maxPred,
                genderRatio: `${menNow}:${womenNow}`,
                crowdLevel: crowdLabelFromPredStore(maxPred),
                recommendLabel: calm?.ts ? `${calmLabel}ごろ` : "確認中",
              },
              sparkline: sparklineFallback,
              sparklineMen: genderSparks.men,
              sparklineWomen: genderSparks.women,
            };
          } catch {
            return null;
          }
        }),
      );

      if (!mounted) return;
      const mapped: Record<
        string,
        {
          stats: RealtimeCardStats;
          sparkline: number[];
          sparklineMen: number[];
          sparklineWomen: number[];
        }
      > = {};
      for (const row of results) {
        if (row) {
          mapped[row.slug] = {
            stats: row.stats,
            sparkline: row.sparkline,
            sparklineMen: row.sparklineMen,
            sparklineWomen: row.sparklineWomen,
          };
        }
      }
      setRelatedRealtime(mapped);
      setRelatedLoading(false);
    })();

    return () => {
      mounted = false;
    };
  }, [digestStores]);

  const favoriteButton = (
    <button
      type="button"
      onClick={() => {
        const next = toggleFavoriteStore(slug);
        setFavorite(next);
      }}
      className="rounded-full border border-amber-400/35 bg-amber-500/10 px-3 py-1.5 text-xs font-medium text-amber-100 transition hover:border-amber-300/60 hover:bg-amber-500/20"
      aria-pressed={favorite}
      aria-label={favorite ? "お気に入りから外す" : "お気に入りに追加"}
    >
      {favorite ? "★ お気に入り済み" : "☆ お気に入りに追加"}
    </button>
  );

  return (
    <div className="space-y-8">
      <MeguribiDashboardPreview headerActions={favoriteButton} />

      <section className="mx-auto w-full max-w-6xl space-y-3 px-4">
        <h2 className="text-sm font-semibold text-slate-100">ほかの店舗を見る</h2>
        <p className="text-[11px] text-slate-500">別店舗の人数・混雑の目安を、カードからすぐに比較できます。</p>
        <div className="grid gap-3 md:grid-cols-4">
          {digestStores.map((store, idx) => (
            <StoreCard
              key={store.slug}
              slug={store.slug}
              label={`Oriental Lounge ${store.label}`}
              brandLabel="ORIENTAL LOUNGE"
              areaLabel={store.areaLabel}
              isHighlight={idx === 0}
              stats={relatedRealtime[store.slug]?.stats}
              sparklinePoints={relatedRealtime[store.slug]?.sparkline}
              sparklineMen={relatedRealtime[store.slug]?.sparklineMen}
              sparklineWomen={relatedRealtime[store.slug]?.sparklineWomen}
              isLoading={relatedLoading && !relatedRealtime[store.slug]}
            />
          ))}
        </div>
      </section>
    </div>
  );
}

export default function StorePage() {
  return (
    <Suspense fallback={<StorePageFallback />}>
      <StorePageInner />
    </Suspense>
  );
}
