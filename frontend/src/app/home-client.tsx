"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { getStoreMetaBySlug, type StoreMeta } from "./config/stores";
import { LAST_STORE_KEY } from "@/lib/browser/meguribiStorage";
import { SHOW_MEGRIBI_JUDGMENTS } from "@/lib/featureFlags";
import {
  STORE_CARD_RANGE_LIMIT,
  STORE_CARD_SPARKLINE_POINTS,
  buildActualSparklineFromRange,
  buildGenderSparklineFromRange,
  parseRangeResponse,
} from "@/lib/storeCardRangeSparkline";
import {
  LastVisitChartSkeleton,
  LastVisitGenderTrendChart,
  LastVisitTotalTrendChart,
} from "@/components/home/LastVisitCharts";
import { FALLBACK_LAST_STORE } from "@/components/home/homeHelpers";
import { HomeHero } from "@/components/home/HomeHero";
import { HomeLastVisitedSection } from "@/components/home/HomeLastVisitedSection";
import { HomeTonightTop5 } from "@/components/home/HomeTonightTop5";
import { HomeStoreDirectory } from "@/components/home/HomeStoreDirectory";
import { HomeBlogStrip } from "@/components/home/HomeBlogStrip";
import { HomeAboutSection } from "@/components/home/HomeAboutSection";
import type {
  HomeBlogTeaser,
  HomeRepresentativeStore,
  HomeMegribiScoreItem,
  MegribiScoreItem,
} from "@/components/home/homeTypes";

export type {
  HomeBlogTeaser,
  HomeRepresentativeStore,
  HomeMegribiScoreItem,
} from "@/components/home/homeTypes";

type HomePageProps = {
  latestBlogPosts: HomeBlogTeaser[];
  /**
   * サーバー側 (page.tsx) で先取りした /api/megribi_score のスナップショット。
   * 取得失敗・タイムアウト時は null（従来通りクライアント fetch のみで描画）。
   */
  initialTop5?: HomeMegribiScoreItem[] | null;
  /**
   * サーバー側 (page.tsx) が STORES（静的データ）から地域ごとに選んだ代表店舗。
   * バックエンドの成否に関係なく raw HTML に /store/ への実アンカーを出すために使う
   * （「今夜のおすすめ」は megribi_score 取得成功時のみリンクが埋まるため、それとは独立）。
   */
  representativeStores?: HomeRepresentativeStore[];
};

type LastVisitFetchedTrend = {
  loading: boolean;
  men: number[];
  women: number[];
  fallbackLine?: number[];
};

/** 相席屋 (ay_*) は total が null（%表示のみ）のため、席の埋まり(%)で判定する */
function hasActivity(d: MegribiScoreItem): boolean {
  return (d.total ?? 0) > 0 || (d.men_seat_pct ?? 0) > 0 || (d.women_seat_pct ?? 0) > 0;
}

export default function HomePage({
  latestBlogPosts,
  initialTop5,
  representativeStores = [],
}: HomePageProps) {
  const [lastStore, setLastStore] = useState<StoreMeta | null>(null);
  const [lastVisitFetched, setLastVisitFetched] = useState<LastVisitFetchedTrend>({
    loading: true,
    men: [],
    women: [],
  });
  // initialTop5 があれば初期HTMLから実データで描画（スケルトン無し）。
  // 無ければ従来通り loading スケルトン→クライアント fetch。
  const seededTop5 = useMemo(
    () => (initialTop5 ? initialTop5.filter(hasActivity).slice(0, 5) : null),
    [initialTop5],
  );
  const [topStores, setTopStores] = useState<MegribiScoreItem[]>(seededTop5 ?? []);
  const [topStoresLoading, setTopStoresLoading] = useState(seededTop5 === null);

  useEffect(() => {
    // 判定表示OFF中は「今夜のおすすめ TOP5」自体が非表示のため取得をスキップする
    // （featureFlags.ts の SHOW_MEGRIBI_JUDGMENTS を true に戻せば fetch は自動的に復活する）。
    if (!SHOW_MEGRIBI_JUDGMENTS) {
      setTopStoresLoading(false);
      return;
    }
    const ac = new AbortController();
    (async () => {
      try {
        const res = await fetch("/api/megribi_score", { signal: ac.signal });
        if (!res.ok) { setTopStoresLoading(false); return; }
        const json = (await res.json()) as { ok: boolean; data?: MegribiScoreItem[] };
        if (!ac.signal.aborted && json.ok && Array.isArray(json.data)) {
          setTopStores(json.data.filter(hasActivity).slice(0, 5));
        }
      } catch {
        /* ignore */
      } finally {
        if (!ac.signal.aborted) setTopStoresLoading(false);
      }
    })();
    return () => ac.abort();
  }, []);

  useEffect(() => {
    try {
      const slug = window.localStorage.getItem(LAST_STORE_KEY);
      if (!slug) return;
      const found = getStoreMetaBySlug(slug);
      setLastStore(found);
    } catch {
      // localStorage が使えない環境では何もしない
    }
  }, []);

  const lastDisplaySlug = lastStore?.slug ?? FALLBACK_LAST_STORE.slug;

  useEffect(() => {
    const ac = new AbortController();
    setLastVisitFetched((p) => ({ ...p, loading: true }));

    (async () => {
      try {
        const rangeRes = await fetch(
          `/api/range?store=${encodeURIComponent(lastDisplaySlug)}&limit=${STORE_CARD_RANGE_LIMIT}`,
          { signal: ac.signal },
        );
        if (!rangeRes.ok) {
          if (!ac.signal.aborted) {
            setLastVisitFetched({ loading: false, men: [], women: [] });
          }
          return;
        }
        const rangeBody: unknown = await rangeRes.json();
        if (ac.signal.aborted) return;
        const rangeRows = parseRangeResponse(rangeBody);
        const genderSparks = buildGenderSparklineFromRange(
          rangeRows,
          STORE_CARD_SPARKLINE_POINTS,
        );
        if (genderSparks.men.length >= 2 && genderSparks.women.length >= 2) {
          setLastVisitFetched({
            loading: false,
            men: genderSparks.men,
            women: genderSparks.women,
          });
          return;
        }
        const line = buildActualSparklineFromRange(rangeRows, STORE_CARD_SPARKLINE_POINTS);
        if (line.length >= 2) {
          setLastVisitFetched({
            loading: false,
            men: [],
            women: [],
            fallbackLine: line,
          });
        } else {
          setLastVisitFetched({ loading: false, men: [], women: [] });
        }
      } catch {
        if (!ac.signal.aborted) {
          setLastVisitFetched({ loading: false, men: [], women: [] });
        }
      }
    })();

    return () => ac.abort();
  }, [lastDisplaySlug]);

  const lastVisitChartBlock = (() => {
    if (lastVisitFetched.loading) {
      return <LastVisitChartSkeleton />;
    }
    if (lastVisitFetched.men.length >= 2 && lastVisitFetched.women.length >= 2) {
      return (
        <LastVisitGenderTrendChart men={lastVisitFetched.men} women={lastVisitFetched.women} />
      );
    }
    if (lastVisitFetched.fallbackLine && lastVisitFetched.fallbackLine.length >= 2) {
      return <LastVisitTotalTrendChart points={lastVisitFetched.fallbackLine} />;
    }
    return (
      <p className="flex h-28 items-center justify-center px-2 text-center text-[11px] text-slate-500">
        直近の推移データを表示できません。
      </p>
    );
  })();

  return (
    <div className="relative min-h-screen bg-black font-display text-slate-50">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_20%_20%,rgba(79,70,229,0.18)_0%,transparent_32%),radial-gradient(circle_at_80%_70%,rgba(236,72,153,0.16)_0%,transparent_32%)]" />

      <div className="relative z-10">
        <main className="mx-auto flex max-w-6xl flex-col gap-10 px-4 py-6 pb-24 md:pb-6">
          <HomeHero />

          <HomeLastVisitedSection lastStore={lastStore} chart={lastVisitChartBlock} />

          {/* 今夜のおすすめ TOP 5 — めぐりびスコア順位が実態と不一致のため一旦非表示
              （featureFlags.ts SHOW_MEGRIBI_JUDGMENTS の doc 参照） */}
          {SHOW_MEGRIBI_JUDGMENTS && (
            <HomeTonightTop5 topStores={topStores} topStoresLoading={topStoresLoading} />
          )}

          <HomeStoreDirectory representativeStores={representativeStores} />

          <HomeBlogStrip latestBlogPosts={latestBlogPosts} />

          <HomeAboutSection />
        </main>

        <div
          className="fixed bottom-0 left-0 right-0 z-40 border-t border-slate-800 bg-black/85 px-4 py-3 backdrop-blur-md md:hidden"
          style={{ paddingBottom: "max(0.75rem, env(safe-area-inset-bottom))" }}
        >
          <Link
            href="/stores"
            className="block w-full rounded-lg bg-indigo-500 py-2.5 text-center text-sm font-semibold text-white shadow-lg shadow-black/30 hover:bg-indigo-400"
          >
            店舗一覧へ
          </Link>
        </div>

        <footer className="mx-auto mt-4 max-w-6xl border-t border-slate-800 px-4 pt-4 pb-6 text-[11px] text-slate-500 md:pb-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap gap-3">
              <Link href="/terms" className="hover:text-slate-300">
                利用規約
              </Link>
              <Link href="/privacy" className="hover:text-slate-300">
                プライバシーポリシー
              </Link>
              <Link href="/contact" className="hover:text-slate-300">
                お問い合わせ
              </Link>
              <Link href="/disclaimer" className="hover:text-slate-300">
                免責事項
              </Link>
            </div>
            <p className="text-slate-600">© めぐりび All Rights Reserved.</p>
          </div>
        </footer>
      </div>
    </div>
  );
}
