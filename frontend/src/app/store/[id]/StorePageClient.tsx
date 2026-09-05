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
} from "@/lib/storeCardRangeSparkline";
import {
  latestCountsOrZero,
  parseRangeEnvelope,
  pickLatestRow,
  type RangeRow,
} from "@/lib/range/rangeRows";
import { ForecastAccuracyCard } from "@/components/ForecastAccuracyCard";
import { DEFAULT_STORE, STORES, STORE_REGION_FILTER_ORDER, distanceKm, getStoreMetaBySlugOrDefault, getStoreMetaBySlugStrict } from "../../config/stores";
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

  const meta = getStoreMetaBySlugOrDefault(slugFromPath || searchParams.get("store") || DEFAULT_STORE);
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

  // 2026-08-26 計測レビュー対応: 従来ここで mount 直後に ?store= をURLへ自動付与していたが、
  // 読み手を全数確認したところ実際に消費している箇所が無かった（このページ自体は
  // slugFromPath を優先、MeguribiDashboardPreview も pathSlug を優先し ?store= は
  // フォールバックとしてしか読まない＝ pathSlug が常に渡るこの経路では到達しない）。
  // 無駄な router.replace（履歴書き換え・非正規URL化）だけが残っていたため削除した。
  // 2026-09-06 訂正: ここには「StoreCard.tsx 等の内部リンクには ?store= 付与が残っている」と
  // 書いてあったが、StoreCard は同じ 2026-08-26 の作業で素の /store/<slug> に直されており
  // （StoreCard.tsx:110）事実に反していた。内部リンクの ?store= は全経路で除去済みで、
  // 最後に残っていたプログラム的な組み立て1箇所も 2026-09-06 に潰した。
  // 再発は frontend/src/lib/internalLinks.test.ts が検問している。

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

  const [reportSummary, setReportSummary] = useState<ReportSummaryData>({
    weekly: null,
    weeklyError: false,
  });

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
          setReportSummary({ weekly: body.weekly ?? null, weeklyError: false });
        } else {
          // 2026-08-21 外部レビュー F11: 503(Supabase障害等)を無言で捨てると
          // 「この店には週報がまだ無い」と区別できなかった。取得失敗を明示する。
          setReportSummary({ weekly: null, weeklyError: true });
        }
      })
      .catch(() => {
        if (!active) return;
        setReportSummary({ weekly: null, weeklyError: true });
      });
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
            const rangeRows = parseRangeEnvelope<RangeRow>({ rows });
            const current = pickLatestRow(rangeRows) ?? {};
            const { men: menNow, women: womenNow, total: nowTotal } = latestCountsOrZero(current);
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
              latestActualTs: typeof current.ts === "string" ? current.ts : null,
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
        // 2026-08-26 計測レビュー対応: 識別子を store_slug に統一（他イベントと揃える）。
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
      {/* 週報の取得に失敗（Supabase障害など）した場合の注記（外部レビュー F11）。
          「週報がまだ無い」との違いが分かるよう、無言でカードを消さない。
          LatestForecastSummaryCard の失敗時表示と言い回し・トーンを揃える。 */}
      {!hasWeeklyReport && reportSummary.weeklyError && (
        <section className="mx-auto w-full max-w-6xl px-4">
          <div className="rounded-2xl border border-white/5 bg-white/[0.02] px-4 py-3">
            <p className="text-[11px] text-white/30">
              週報を取得できませんでした。しばらくすると自動的に更新されます。
            </p>
          </div>
        </section>
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
        fromSlug={slug}
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
    // fallback にも initialSnapshot を渡す。StorePageInner は useSearchParams() を使うため
    // 静的プリレンダ時にこの Suspense 境界が CSR へ bail し、生成されるHTMLには fallback だけが
    // 焼かれる。つまり fallback が「クローラが読めるテキストを出せる唯一の場所」であり、
    // ここでサーバー取得済みの実データ（人数・男女比・ピーク・最終更新）をテキスト描画する。
    // ハイドレーション後は下の StorePageInner に差し替わるので最終的な画面は変わらない。
    <Suspense fallback={<StorePageFallback initialSnapshot={initialSnapshot} />}>
      <StorePageInner initialSnapshot={initialSnapshot} />
    </Suspense>
  );
}
