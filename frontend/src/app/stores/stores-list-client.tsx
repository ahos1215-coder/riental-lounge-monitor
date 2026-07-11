"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { SHOW_MEGRIBI_JUDGMENTS } from "@/lib/featureFlags";
import { StoreCard } from "@/components/StoreCard";
import {
  BRAND_DISPLAY_LABEL,
  STORES,
  STORE_REGION_FILTER_ORDER,
  buildStoreFullName,
  type StoreMeta,
} from "../config/stores";
import {
  STORE_CARD_RANGE_LIMIT,
  STORE_CARD_SPARKLINE_POINTS,
  buildActualSparklineSeriesFromRange,
  buildGenderSparklineSeriesFromRange,
  parseRangeResponse,
  pickLatestRangeRow,
} from "@/lib/storeCardRangeSparkline";
import {
  STORES_PER_PAGE,
  crowdLabelFromPred,
  toHmJst,
  type BrandFilter,
  type ForecastPoint,
} from "./storesListHelpers";
import { StoresFilterBar } from "./StoresFilterBar";
import { StoresPagination } from "./StoresPagination";
import { StoresStatsFooter } from "./StoresStatsFooter";

/** page.tsx（サーバー snapshot）とクライアント側 fetch の両方で使う共通シェイプ。 */
export type StoreRealtimeCard = {
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
  /** sparkline と同順・同数の各点タイムスタンプ(epoch ms)。閉店ギャップで折れ線分割に使う。 */
  sparklineTimes?: number[];
  sparklineMen: number[];
  sparklineWomen: number[];
  /** sparklineMen/Women と同順・同数の各点タイムスタンプ(epoch ms)。 */
  sparklineGenderTimes?: number[];
  forecastPending?: boolean;
  megribiScore?: number | null;
};

export type StoresListClientProps = {
  /**
   * サーバー側 (page.tsx) で先取りした「デフォルト表示（フィルタ無し・1ページ目）」12店舗分の
   * range_multi + megribi_score スナップショット。forecast（crowdLevel/recommendLabel等）は
   * 含まない“部分カード”状態（クライアント側が range 到着直後に出す状態と同じ形）。
   * URL にフィルタ/ページ指定がある場合はこの prop を無視し、従来通りクライアント fetch のみで描画する。
   */
  initialCards?: Record<string, StoreRealtimeCard> | null;
};

export default function StoresListClient({ initialCards }: StoresListClientProps = {}) {
  const searchParams = useSearchParams();
  const pathname = usePathname();
  const router = useRouter();

  // サーバー snapshot (initialCards) は「フィルタ無し・1ページ目」の12店舗分でのみ有効。
  // region/page が URL に付いている初回マウントでは使わない（対象店舗が一致しないため）。
  // useState の lazy initializer はマウント時の1回しか評価されないため、ここでの
  // searchParams 参照は「初回レンダー時点の値」として固定される（ref化は不要）。
  const [storeRealtime, setStoreRealtime] = useState<Record<string, StoreRealtimeCard>>(() => {
    const isDefaultViewOnMount = !searchParams.get("region") && !searchParams.get("page");
    return isDefaultViewOnMount && initialCards ? initialCards : {};
  });
  const [realtimeLoading, setRealtimeLoading] = useState(() => {
    const isDefaultViewOnMount = !searchParams.get("region") && !searchParams.get("page");
    return !(isDefaultViewOnMount && initialCards);
  });

  const [brandFilter, setBrandFilter] = useState<BrandFilter>("all");
  const [query, setQuery] = useState("");

  const replaceQueryParams = useCallback(
    (mutate: (p: URLSearchParams) => void) => {
      const p = new URLSearchParams(searchParams.toString());
      mutate(p);
      const qs = p.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [searchParams, pathname, router],
  );

  const regionTabIds = useMemo(() => {
    const inData = new Set(STORES.map((s) => s.regionLabel));
    return STORE_REGION_FILTER_ORDER.filter((id) => inData.has(id));
  }, []);

  const regionParam = searchParams.get("region");
  const regionFilter = useMemo(() => {
    if (!regionParam) return null;
    const rid = regionParam.trim();
    return regionTabIds.includes(rid) ? rid : null;
  }, [regionParam, regionTabIds]);

  const rawPage = searchParams.get("page");
  const parsedPage = rawPage ? parseInt(rawPage, 10) : NaN;
  const pageFromUrl =
    Number.isFinite(parsedPage) && parsedPage >= 1 ? Math.floor(parsedPage) : 1;

  const filteredStores: StoreMeta[] = useMemo(() => {
    let list = [...STORES];

    if (brandFilter !== "all") {
      list = list.filter((s) => s.brand === brandFilter);
    }

    if (regionFilter !== null) {
      list = list.filter((s) => s.regionLabel === regionFilter);
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
  }, [brandFilter, query, regionFilter]);

  const pageCount = Math.max(1, Math.ceil(filteredStores.length / STORES_PER_PAGE));
  const currentPage = Math.min(Math.max(1, pageFromUrl), pageCount);

  const pagedStores = useMemo(
    () =>
      filteredStores.slice(
        (currentPage - 1) * STORES_PER_PAGE,
        currentPage * STORES_PER_PAGE,
      ),
    [filteredStores, currentPage],
  );

  useEffect(() => {
    if (pageFromUrl > pageCount && pageCount >= 1) {
      replaceQueryParams((p) => {
        if (pageCount <= 1) p.delete("page");
        else p.set("page", String(pageCount));
      });
    }
  }, [pageFromUrl, pageCount, replaceQueryParams]);

  const prevQueryRef = useRef<string | null>(null);
  useEffect(() => {
    if (prevQueryRef.current === null) {
      prevQueryRef.current = query;
      return;
    }
    if (prevQueryRef.current === query) return;
    prevQueryRef.current = query;
    const t = window.setTimeout(() => {
      replaceQueryParams((p) => {
        p.delete("page");
      });
    }, 400);
    return () => clearTimeout(t);
  }, [query, replaceQueryParams]);

  const skipScrollOnMount = useRef(true);
  useEffect(() => {
    if (skipScrollOnMount.current) {
      skipScrollOnMount.current = false;
      return;
    }
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, [currentPage]);

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    const targets = pagedStores;
    // 対象12店舗すべてのカードが既にある（サーバー snapshot による seed、または
    // 直前の取得結果）なら、裏で最新データを取りに行きつつ既存カードを表示し続ける
    // （setStoreRealtime({}) でスケルトンに戻すとサーバー snapshot の意味が無くなるため）。
    const alreadyHasAllTargets =
      targets.length > 0 && targets.every((t) => storeRealtime[t.slug] !== undefined);

    if (targets.length === 0) {
      setStoreRealtime({});
      setRealtimeLoading(false);
      return () => controller.abort();
    }

    if (!alreadyHasAllTargets) {
      setRealtimeLoading(true);
      setStoreRealtime({});
    }

    function isAbortError(err: unknown): boolean {
      return (
        (err instanceof DOMException && err.name === "AbortError") ||
        (err instanceof Error && err.name === "AbortError")
      );
    }

    void (async () => {
      const slugsCsv = targets.map((t) => t.slug).join(",");
      type ForecastBatchBody = { ok?: boolean; by_slug?: Record<string, { data?: ForecastPoint[] }> };
      type RangeBatchResult = {
        ok: boolean;
        bySlug: Map<string, ReturnType<typeof parseRangeResponse>>;
      };

      // ① range_multi・forecast_today_multi・megribi_score を完全並列で発火する。
      // 旧実装は range_multi の完了を await してから forecast/megribi を発火しており、
      // コールド時（range 3-6s + forecast 8-9s）の待ち時間が直列に積み上がって
      // 最悪 10 秒超になっていた。3つとも独立 state 更新なので、range が届き次第
      // カードを部分表示し、forecast/megribi は届き次第チップを埋める
      // （体感の待ち時間は合計ではなく max(...) で頭打ちになる）。
      const rangeMultiPromise: Promise<RangeBatchResult> = fetch(
        `/api/range_multi?stores=${encodeURIComponent(slugsCsv)}&limit=${STORE_CARD_RANGE_LIMIT}`,
        { signal },
      )
        .then(async (r) => {
          if (!r.ok) return { ok: false, bySlug: new Map() };
          const j = (await r.json()) as {
            ok?: boolean;
            by_slug?: Record<string, { rows?: unknown[] }>;
          };
          if (!j?.ok || !j?.by_slug || typeof j.by_slug !== "object") {
            return { ok: false, bySlug: new Map() };
          }
          const bySlug = new Map<string, ReturnType<typeof parseRangeResponse>>();
          for (const s of targets) {
            const rows = j.by_slug[s.slug]?.rows ?? [];
            bySlug.set(s.slug, parseRangeResponse({ rows }));
          }
          return { ok: true, bySlug };
        })
        // フォールバックで個別 /api/range に任せる（batchOk=false 相当）
        .catch(() => ({ ok: false, bySlug: new Map() }));

      // 判定表示OFF中は一覧カードの判定バッジ自体が非表示のため取得をスキップする
      // （featureFlags.ts の SHOW_MEGRIBI_JUDGMENTS を true に戻せば fetch は自動的に復活する）。
      const megribiPromise = !SHOW_MEGRIBI_JUDGMENTS
        ? Promise.resolve()
        : (async () => {
            try {
              const mRes = await fetch(
                `/api/megribi_score?stores=${encodeURIComponent(slugsCsv)}`,
                { signal },
              );
              if (!signal.aborted && mRes.ok) {
                // megribi_score は {ok, data:[{slug,score}]} 形式。slug->score の Map にする。
                const mJson = (await mRes.json()) as { ok?: boolean; data?: { slug: string; score?: number }[] };
                const scoreMap = new Map<string, number>();
                if (Array.isArray(mJson.data)) {
                  for (const it of mJson.data) {
                    if (it && typeof it.slug === "string" && typeof it.score === "number") {
                      scoreMap.set(it.slug, it.score);
                    }
                  }
                }
                if (!signal.aborted) {
                  setStoreRealtime((prev) => {
                    const next = { ...prev };
                    for (const t of targets) {
                      const score = scoreMap.has(t.slug) ? (scoreMap.get(t.slug) as number) : null;
                      if (next[t.slug]) {
                        next[t.slug] = { ...next[t.slug], megribiScore: score };
                      }
                    }
                    return next;
                  });
                }
              }
            } catch {
              // スコア取得失敗は非致命的
            }
          })();

      const forecastBatchPromise: Promise<ForecastBatchBody | null> = fetch(
        `/api/forecast_today_multi?stores=${encodeURIComponent(slugsCsv)}`,
        { signal },
      )
        .then((r) => (r.ok ? (r.json() as Promise<ForecastBatchBody>) : null))
        .catch(() => null);

      async function fetchStoreCard(store: StoreMeta): Promise<void> {
        let menNow = 0;
        let womenNow = 0;
        let nowTotal = 0;
        let actualSparkline: number[] = [];
        let sparklineTimes: number[] = [];
        let sparklineMen: number[] = [];
        let sparklineWomen: number[] = [];
        let sparklineGenderTimes: number[] = [];

        try {
          const rangeMulti = await rangeMultiPromise;
          if (signal.aborted) return;
          let rangeRows: ReturnType<typeof parseRangeResponse>;
          if (rangeMulti.ok && rangeMulti.bySlug.has(store.slug)) {
            rangeRows = rangeMulti.bySlug.get(store.slug)!;
          } else {
            // バッチ失敗時のみ個別 /api/range にフォールバック
            const rangeRes = await fetch(
              `/api/range?store=${encodeURIComponent(store.slug)}&limit=${STORE_CARD_RANGE_LIMIT}`,
              { signal },
            );
            if (signal.aborted) return;
            if (!rangeRes.ok) return;
            const rangeBody: unknown = await rangeRes.json();
            if (signal.aborted) return;
            rangeRows = parseRangeResponse(rangeBody);
          }

          const actualSeries = buildActualSparklineSeriesFromRange(
            rangeRows,
            STORE_CARD_SPARKLINE_POINTS,
          );
          actualSparkline = actualSeries.values;
          sparklineTimes = actualSeries.times;
          const genderSparks = buildGenderSparklineSeriesFromRange(
            rangeRows,
            STORE_CARD_SPARKLINE_POINTS,
          );
          sparklineMen = genderSparks.men;
          sparklineWomen = genderSparks.women;
          sparklineGenderTimes = genderSparks.times;
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
            sparklineTimes,
            sparklineMen,
            sparklineWomen,
            sparklineGenderTimes,
            forecastPending: true,
          };
          setStoreRealtime((prev) => ({ ...prev, [store.slug]: partialCard }));
        } catch (err) {
          if (signal.aborted || isAbortError(err)) return;
          return;
        }

        try {
          // バッチ forecast（並列発火済み）を待って使う。バッチ失敗時のみ個別フォールバック。
          let forecastRows: ForecastPoint[] = [];
          const batchBody = await forecastBatchPromise;
          if (signal.aborted) return;
          const batchData = batchBody?.by_slug?.[store.slug]?.data;
          if (Array.isArray(batchData)) {
            forecastRows = batchData;
          } else {
            // batch 失敗 → 個別フォールバック
            const fallbackRes = await fetch(
              `/api/forecast_today?store=${encodeURIComponent(store.slug)}`,
              { signal },
            ).catch(() => null);
            if (signal.aborted) return;
            if (fallbackRes?.ok) {
              const fb = (await fallbackRes.json().catch(() => ({}))) as { data?: ForecastPoint[] };
              forecastRows = Array.isArray(fb?.data) ? fb.data : [];
            }
          }

          if (signal.aborted) return;

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
            sparklineTimes,
            sparklineMen,
            sparklineWomen,
            sparklineGenderTimes,
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
                  crowdLevel: "予測準備中",
                  recommendLabel: "予測準備中",
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

      if (!signal.aborted) {
        // 部分カード描画（range 到着次第）+ forecast/megribi 到着待ちを全店舗ぶん並行実行。
        // range_multi・forecast_today_multi・megribi_score 自体は既に上で並列発火済み。
        const forecastPromises = targets.map((store) => fetchStoreCard(store));

        await Promise.all([...forecastPromises, megribiPromise]);
      }

      if (!signal.aborted) {
        setRealtimeLoading(false);
      }
    })();

    return () => {
      controller.abort();
      setRealtimeLoading(false);
    };
    // storeRealtime は「初回マウント時に seed 済みか」を1回だけ判定するために読むだけで、
    // 依存に加えると更新のたびにこの取得エフェクト自体が再実行されてしまうため意図的に除外。
  }, [pagedStores]); // eslint-disable-line react-hooks/exhaustive-deps

  // JIS は未実装 (スクレイピング未対応)。相席屋は対応済み
  const isComingSoonBrand = brandFilter === "jis";

  const registeredCount = STORES.length;
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
              めぐりびで掲載している相席ラウンジ（オリエンタルラウンジ・相席屋）の店舗一覧です。カードを開くと、人数・混雑の目安・グラフ付きの店舗ページへ移動します。
            </p>
          </section>

          <StoresFilterBar
            query={query}
            setQuery={setQuery}
            brandFilter={brandFilter}
            setBrandFilter={setBrandFilter}
            replaceQueryParams={replaceQueryParams}
            regionFilter={regionFilter}
            regionTabIds={regionTabIds}
          />

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
              <>
                <div className="grid gap-4 md:grid-cols-3">
                  {pagedStores.map((store, idx) => (
                    <StoreCard
                      key={store.slug}
                      slug={store.slug}
                      label={buildStoreFullName(store)}
                      brandLabel={BRAND_DISPLAY_LABEL[store.brand]}
                      brand={store.brand}
                      capacity={store.capacity}
                      areaLabel={store.areaLabel}
                      isHighlight={idx === 0}
                      stats={storeRealtime[store.slug]?.stats}
                      sparklinePoints={storeRealtime[store.slug]?.sparkline}
                      sparklineTimes={storeRealtime[store.slug]?.sparklineTimes}
                      sparklineMen={storeRealtime[store.slug]?.sparklineMen}
                      sparklineWomen={storeRealtime[store.slug]?.sparklineWomen}
                      sparklineGenderTimes={storeRealtime[store.slug]?.sparklineGenderTimes}
                      forecastPending={storeRealtime[store.slug]?.forecastPending}
                      isLoading={realtimeLoading && !storeRealtime[store.slug]}
                      megribiScore={storeRealtime[store.slug]?.megribiScore}
                    />
                  ))}
                </div>
                {pageCount > 1 ? (
                  <StoresPagination
                    currentPage={currentPage}
                    pageCount={pageCount}
                    totalStores={filteredStores.length}
                    replaceQueryParams={replaceQueryParams}
                  />
                ) : null}
              </>
            )}
          </section>

          <StoresStatsFooter
            registeredCount={registeredCount}
            regionCount={regionCount}
            areaExamples={areaExamples}
          />
        </div>
      </div>
    </div>
  );
}
