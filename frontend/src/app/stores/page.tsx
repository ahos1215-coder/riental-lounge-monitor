"use client";

import { useMemo, useState } from "react";
import { StoreCard } from "@/components/StoreCard";
import { STORES, type StoreMeta } from "../config/stores";
import { useEffect } from "react";
import {
  STORE_CARD_RANGE_LIMIT,
  STORE_CARD_SPARKLINE_POINTS,
  buildActualSparklineFromRange,
  buildGenderSparklineFromRange,
  parseRangeResponse,
  pickLatestRangeRow,
} from "@/lib/storeCardRangeSparkline";

type BrandFilter = "all" | "oriental" | "jis" | "aisekiya";
type ForecastPoint = { ts: string; total_pred?: number };
type StoreRealtimeCard = {
  slug: string;
  stats: {
    menCount: number;
    womenCount: number;
    nowTotal: number;
    peakPredTotal: number;
    genderRatio: string;
    crowdLevel: string;
    recommendLabel: string;
  };
  sparkline: number[];
  sparklineMen: number[];
  sparklineWomen: number[];
  /** true の間は予測API待ち（実測のみ表示） */
  forecastPending?: boolean;
};

const BRAND_TABS: { id: BrandFilter; label: string }[] = [
  { id: "all", label: "すべて" },
  { id: "oriental", label: "ORIENTAL LOUNGE" },
  { id: "jis", label: "JIS" },
  { id: "aisekiya", label: "相席屋" },
];

/** 同時に飛ばす店舗数。Render 側の予測APIが重いため多すぎると全体が遅延しやすい */
const STORE_LIST_FETCH_CONCURRENCY = 6;

export default function StoresPage() {
  const [brandFilter, setBrandFilter] = useState<BrandFilter>("all");
  const [query, setQuery] = useState("");
  const [storeRealtime, setStoreRealtime] = useState<Record<string, StoreRealtimeCard>>({});
  const [realtimeLoading, setRealtimeLoading] = useState(false);

  const filteredStores: StoreMeta[] = useMemo(() => {
    let list = [...STORES];

    if (brandFilter === "oriental") {
      list = list.filter((s) => s.brand === "oriental");
    }
    if (brandFilter === "jis" || brandFilter === "aisekiya") {
      list = [];
    }

    if (query.trim()) {
      const q = query.trim().toLowerCase();
      list = list.filter(
        (s) =>
          s.label.toLowerCase().includes(q) ||
          s.areaLabel.toLowerCase().includes(q),
      );
    }

    return list;
  }, [brandFilter, query]);

  const toHmJst = (iso: string): string =>
    new Intl.DateTimeFormat("ja-JP", {
      timeZone: "Asia/Tokyo",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(new Date(iso));

  const crowdLabelFromPred = (maxPred: number): string => {
    if (maxPred >= 120) return "混雑";
    if (maxPred >= 80) return "ほどよい";
    return "空いている";
  };

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    const targets = filteredStores.slice(0, 24);

    if (targets.length === 0) {
      setStoreRealtime({});
      setRealtimeLoading(false);
      return () => controller.abort();
    }

    setRealtimeLoading(true);
    setStoreRealtime({});

    function isAbortError(err: unknown): boolean {
      return (
        (err instanceof DOMException && err.name === "AbortError") ||
        (err instanceof Error && err.name === "AbortError")
      );
    }

    async function fetchStoreCard(store: StoreMeta): Promise<void> {
      let menNow = 0;
      let womenNow = 0;
      let nowTotal = 0;
      let actualSparkline: number[] = [];
      let sparklineMen: number[] = [];
      let sparklineWomen: number[] = [];

      try {
        const rangeRes = await fetch(
          `/api/range?store=${encodeURIComponent(store.slug)}&limit=${STORE_CARD_RANGE_LIMIT}`,
          { cache: "no-store", signal },
        );
        if (signal.aborted) return;
        if (!rangeRes.ok) return;
        const rangeBody: unknown = await rangeRes.json();
        if (signal.aborted) return;

        const rangeRows = parseRangeResponse(rangeBody);
        actualSparkline = buildActualSparklineFromRange(
          rangeRows,
          STORE_CARD_SPARKLINE_POINTS,
        );
        const genderSparks = buildGenderSparklineFromRange(
          rangeRows,
          STORE_CARD_SPARKLINE_POINTS,
        );
        sparklineMen = genderSparks.men;
        sparklineWomen = genderSparks.women;
        const current = pickLatestRangeRow(rangeRows) ?? {};
        menNow = Math.max(0, Math.round(Number(current.men ?? 0)));
        womenNow = Math.max(0, Math.round(Number(current.women ?? 0)));
        nowTotal = Math.max(0, Math.round(Number(current.total ?? menNow + womenNow)));

        const partialCard: StoreRealtimeCard = {
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
        };
        setStoreRealtime((prev) => ({ ...prev, [store.slug]: partialCard }));
      } catch (err) {
        if (signal.aborted || isAbortError(err)) return;
        return;
      }

      try {
        const forecastRes = await fetch(
          `/api/forecast_today?store=${encodeURIComponent(store.slug)}`,
          { cache: "no-store", signal },
        );
        if (signal.aborted) return;
        if (!forecastRes.ok) throw new Error(`forecast ${forecastRes.status}`);
        const forecastBody = (await forecastRes.json()) as { data?: ForecastPoint[] };
        if (signal.aborted) return;

        const forecastRows = Array.isArray(forecastBody?.data) ? forecastBody.data : [];
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
        const calmLabel = calm?.ts ? toHmJst(calm.ts) : "--:--";

        const fullCard: StoreRealtimeCard = {
          slug: store.slug,
          stats: {
            menCount: menNow,
            womenCount: womenNow,
            nowTotal,
            peakPredTotal: maxPred,
            genderRatio: `${menNow}:${womenNow}`,
            crowdLevel: crowdLabelFromPred(maxPred),
            recommendLabel: calm?.ts ? `${calmLabel}ごろ` : "確認中",
          },
          sparkline: actualSparkline,
          sparklineMen,
          sparklineWomen,
          forecastPending: false,
        };
        if (signal.aborted) return;
        setStoreRealtime((prev) => ({ ...prev, [store.slug]: fullCard }));
      } catch (err) {
        if (signal.aborted || isAbortError(err)) return;
        setStoreRealtime((prev) => {
          const cur = prev[store.slug];
          if (!cur) return prev;
          return {
            ...prev,
            [store.slug]: {
              ...cur,
              stats: {
                ...cur.stats,
                peakPredTotal: 0,
                crowdLevel: "確認中",
                recommendLabel: "確認中",
              },
              sparkline: cur.sparkline,
              sparklineMen: cur.sparklineMen,
              sparklineWomen: cur.sparklineWomen,
              forecastPending: false,
            },
          };
        });
      }
    }

    let nextIndex = 0;
    async function worker(): Promise<void> {
      while (true) {
        const i = nextIndex++;
        if (i >= targets.length) break;
        await fetchStoreCard(targets[i]!);
      }
    }

    const poolSize = Math.min(STORE_LIST_FETCH_CONCURRENCY, targets.length);
    void Promise.all(Array.from({ length: poolSize }, () => worker())).finally(() => {
      if (!signal.aborted) {
        setRealtimeLoading(false);
      }
    });

    return () => {
      controller.abort();
      setRealtimeLoading(false);
    };
  }, [filteredStores]);

  const isComingSoonBrand =
    brandFilter === "jis" || brandFilter === "aisekiya";

  const registeredCount = STORES.length;
  /** 大エリア（regionLabel）のユニーク数 — 営業状況とは未連携 */
  const regionCount = useMemo(
    () => new Set(STORES.map((s) => s.regionLabel)).size,
    [],
  );
  const areaExamples =
    STORES.slice(0, 3)
      .map((s) => s.areaLabel)
      .join(" / ") || "—";

  return (
    <div className="relative min-h-screen w-full overflow-x-hidden bg-[#050505] font-display text-white">
      <div className="absolute inset-0 z-0 bg-[radial-gradient(circle_at_20%_20%,rgba(79,70,229,0.12)_0%,transparent_30%),radial-gradient(circle_at_80%_70%,rgba(236,72,153,0.08)_0%,transparent_30%)]" />

      <div className="relative z-10 flex justify-center">
        <div className="flex min-h-screen w-full max-w-[1080px] flex-col px-4">
          <section className="pb-4 pt-2">
            <h1 className="text-[26px] font-bold tracking-[-0.03em]">
              店舗一覧
            </h1>
            <p className="mt-2 max-w-2xl text-sm leading-relaxed text-white/70">
              めぐりびで掲載しているオリエンタルラウンジの店舗一覧です。カードを開くと、人数・混雑の目安・グラフ付きの店舗ページへ移動します。
            </p>
          </section>

          <section>
            <div className="rounded-xl border border-white/10 bg-black/50 p-4">
              <div className="flex flex-wrap items-center gap-3">
                <div className="flex min-w-[220px] flex-1 items-center rounded-full border border-slate-700 bg-slate-950 px-3 py-1.5 text-xs text-slate-200">
                  <span className="mr-2 text-[13px] text-slate-400">🔍</span>
                  <input
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="店舗名・エリアで検索（例：渋谷、福岡）"
                    className="flex-1 bg-transparent text-xs outline-none placeholder:text-slate-500"
                  />
                </div>

                <div className="flex flex-wrap items-center gap-1">
                  {BRAND_TABS.map((tab) => (
                    <button
                      key={tab.id}
                      type="button"
                      onClick={() => setBrandFilter(tab.id)}
                      className={[
                        "rounded-full px-3 py-1 text-[11px] font-medium transition",
                        brandFilter === tab.id
                          ? "bg-slate-100 text-slate-900"
                          : "bg-slate-900/60 text-slate-300 hover:bg-slate-800",
                      ].join(" ")}
                    >
                      {tab.label}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </section>

          <section className="space-y-3 py-4">
            {isComingSoonBrand ? (
              <div className="rounded-2xl border border-dashed border-slate-700 bg-slate-950/70 p-6 text-center text-xs text-slate-400">
                <p>
                  このブランドの対応は現在準備中です。まずは ORIENTAL LOUNGE から順次対応しています。
                </p>
              </div>
            ) : filteredStores.length === 0 ? (
              <div className="rounded-2xl border border-slate-800 bg-slate-950/80 p-6 text-center text-xs text-slate-400">
                検索条件に一致する店舗が見つかりませんでした。
              </div>
            ) : (
              <div className="grid gap-4 md:grid-cols-3">
                {filteredStores.map((store, idx) => (
                  <StoreCard
                    key={store.slug}
                    slug={store.slug}
                    label={`オリエンタルラウンジ ${store.label}`}
                    brandLabel="ORIENTAL LOUNGE"
                    areaLabel={store.areaLabel}
                    isHighlight={idx === 0}
                    stats={storeRealtime[store.slug]?.stats}
                    sparklinePoints={storeRealtime[store.slug]?.sparkline}
                    sparklineMen={storeRealtime[store.slug]?.sparklineMen}
                    sparklineWomen={storeRealtime[store.slug]?.sparklineWomen}
                    forecastPending={storeRealtime[store.slug]?.forecastPending}
                    isLoading={realtimeLoading && !storeRealtime[store.slug]}
                  />
                ))}
              </div>
            )}
          </section>

          <section className="grid gap-3 pb-10 md:grid-cols-3">
            <div className="rounded-2xl border border-slate-800 bg-slate-950/80 p-3 text-xs">
              <p className="text-[11px] text-slate-400">登録店舗数</p>
              <p className="mt-1 text-2xl font-semibold text-slate-50">
                {registeredCount}
              </p>
            </div>
            <div className="rounded-2xl border border-slate-800 bg-slate-950/80 p-3 text-xs">
              <p className="text-[11px] text-slate-400">
                カバーする大エリア数（region）
              </p>
              <p className="mt-1 text-2xl font-semibold text-slate-50">
                {regionCount}
              </p>
              <p className="mt-1 text-[10px] text-slate-500">
                営業中かどうかのリアルタイム表示は未連携です。
              </p>
            </div>
            <div className="rounded-2xl border border-slate-800 bg-slate-950/80 p-3 text-xs">
              <p className="text-[11px] text-slate-400">
                掲載エリアの例（先頭3店）
              </p>
              <p className="mt-1 text-base font-semibold leading-snug text-slate-50">
                {areaExamples}
              </p>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
