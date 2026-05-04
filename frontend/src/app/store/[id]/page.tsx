"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { StoreCard } from "@/components/StoreCard";
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
import { DEFAULT_STORE, STORES, getStoreMetaBySlug, getStoreMetaBySlugStrict } from "../../config/stores";

type ReportSummaryItem = {
  bullets: string[];
  heading: string | null;
  updatedAt: string;
  targetDate: string;
} | null;

type ReportSummaryData = {
  // Daily カードは v2 で削除済 (LatestForecastSummaryCard の「今日の傾向まとめ」に統合)。
  // ここでは weekly のみ保持する。
  weekly: ReportSummaryItem;
};

type RealtimeCardStats = {
  menCount: number;
  womenCount: number;
  nowTotal: number;
  peakPredTotal: number;
  genderRatio: string;
  crowdLevel?: string;
  recommendLabel?: string;
};


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

  // URLパスの店舗slugが不正な場合は店舗一覧へリダイレクト
  const strictMeta = getStoreMetaBySlugStrict(slugFromPath);
  useEffect(() => {
    if (slugFromPath && !strictMeta) {
      router.replace("/stores");
    }
  }, [slugFromPath, strictMeta, router]);

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
    sendEvent("store_view", { store_slug: slug, store_label: meta.label });
  }, [slug]);

  const digestStores = useMemo(
    () => STORES.filter((s) => s.slug !== slug).slice(0, 4),
    [slug],
  );

  const [reportSummary, setReportSummary] = useState<ReportSummaryData>({ weekly: null });

  useEffect(() => {
    if (!slug) return;
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
  }, [slug]);

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

        const mapped: Record<
          string,
          {
            stats: RealtimeCardStats;
            sparkline: number[];
            sparklineMen: number[];
            sparklineWomen: number[];
          }
        > = {};
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
  }, [digestStores]);

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
      <MeguribiDashboardPreview headerActions={favoriteButton} />

      {/* AI レポート要約セクション（Weekly Report のみ） */}
      {hasWeeklyReport && (
        <section className="mx-auto w-full max-w-6xl px-4">
          <h2 className="mb-3 text-sm font-semibold text-slate-100">AI 予測レポート</h2>
          <div className="grid gap-3">
            {/* Weekly Report */}
            {reportSummary.weekly && (
              <div className="rounded-2xl border border-amber-500/30 bg-amber-500/5 p-4">
                <div className="flex items-center justify-between gap-2">
                  <span className="inline-flex items-center rounded-md bg-amber-500/20 px-2 py-0.5 text-[11px] font-bold text-amber-200">
                    Weekly Report
                  </span>
                  <span className="text-[11px] text-white/40">{reportSummary.weekly.updatedAt} 更新</span>
                </div>
                {reportSummary.weekly.heading && (
                  <p className="mt-2 text-sm font-bold leading-snug text-white line-clamp-2">
                    {reportSummary.weekly.heading}
                  </p>
                )}
                {reportSummary.weekly.bullets.length > 0 && (
                  <ul className="mt-2 space-y-1">
                    {reportSummary.weekly.bullets.map((b, i) => (
                      <li key={i} className="flex items-start gap-1.5 text-xs text-white/75">
                        <span className="mt-0.5 shrink-0 text-amber-300">▸</span>
                        <span className="line-clamp-2">{b}</span>
                      </li>
                    ))}
                  </ul>
                )}
                <Link
                  href={`/reports/weekly/${encodeURIComponent(slug)}`}
                  className="mt-3 inline-flex items-center gap-1 text-xs font-semibold text-amber-300 hover:text-amber-200"
                >
                  詳しく見る <span aria-hidden>→</span>
                </Link>
              </div>
            )}
          </div>
          <div className="mt-3">
            <Link
              href="/reports"
              className="text-xs text-indigo-300 hover:text-indigo-200"
            >
              AI予測レポート一覧 →
            </Link>
          </div>
        </section>
      )}

      <section className="mx-auto w-full max-w-6xl px-4">
        <div className="max-w-xs">
          <ForecastAccuracyCard storeSlug={slug} />
        </div>
      </section>

      <section className="mx-auto w-full max-w-6xl space-y-3 px-4">
        <h2 className="text-sm font-semibold text-slate-100">ほかの店舗を見る</h2>
        <p className="text-[11px] text-slate-500">別店舗の人数・混雑の目安を、カードからすぐに比較できます。</p>
        <div className="grid gap-3 md:grid-cols-4">
          {digestStores.map((store, idx) => (
            <StoreCard
              key={store.slug}
              slug={store.slug}
              label={store.label}
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
