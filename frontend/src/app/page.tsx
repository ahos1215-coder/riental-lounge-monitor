"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  DEFAULT_STORE,
  STORES,
  getStoreMetaBySlug,
  type StoreMeta,
} from "./config/stores";
import { StoreCard } from "@/components/StoreCard";

// --------------------------------------
// 型定義
// --------------------------------------

type NearStore = {
  id: string;
  name: string;
  maleRatio: string;
  femaleRatio: string;
  tags: string[];
};

type FeaturedStore = {
  id: string;
  name: string;
  maleRatio: string;
  femaleRatio: string;
  area: string;
  crowdLevel: string;
  peakTime: string;
  rank: number;
  recommendScore: number;
};

type BlogArticle = {
  id: number;
  title: string;
  category: string;
  imageUrl: string;
};

// --------------------------------------
// 定数
// --------------------------------------

const LAST_STORE_KEY = "meguribi:lastStoreSlug";

const DEFAULT_STORE_META = getStoreMetaBySlug(DEFAULT_STORE);

// 近くの店舗（ダミー）
const NEAR_STORES: NearStore[] = [
  {
    id: "alchemist",
    name: "The Alchemist",
    maleRatio: "7",
    femaleRatio: "3",
    tags: ["オトナ向け", "落ち着いた雰囲気"],
  },
  {
    id: "lounge88",
    name: "Lounge 88",
    maleRatio: "6",
    femaleRatio: "4",
    tags: ["ソファ", "ワイワイ"],
  },
  {
    id: "aquavitae",
    name: "Aqua Vitae",
    maleRatio: "7",
    femaleRatio: "3",
    tags: ["カウンター", "しっとり"],
  },
];

// 今夜のおすすめ（ダミー）
const FEATURED_STORES: FeaturedStore[] = [
  {
    id: "ginza",
    name: "Ginza Highball",
    maleRatio: "6",
    femaleRatio: "4",
    area: "東京都・中央区",
    crowdLevel: "やや混み",
    peakTime: "21:00",
    rank: 1,
    recommendScore: 92,
  },
  {
    id: "shibuya",
    name: "Shibuya Sky Lounge",
    maleRatio: "4",
    femaleRatio: "6",
    area: "東京都・渋谷区",
    crowdLevel: "ピーク手前",
    peakTime: "22:00",
    rank: 2,
    recommendScore: 88,
  },
  {
    id: "shinjuku",
    name: "Old Oak Shinjuku",
    maleRatio: "7",
    femaleRatio: "3",
    area: "東京都・新宿区",
    crowdLevel: "ほどよく",
    peakTime: "20:30",
    rank: 3,
    recommendScore: 85,
  },
];

// ブログ記事（ダミー）
const BLOG_ARTICLES: BlogArticle[] = [
  {
    id: 1,
    title: "今、飲むべきミクソロジーの世界",
    category: "特集",
    imageUrl: "/images/blog-mixology.jpg",
  },
  {
    id: 2,
    title: "トップバーテンダーが語る、一杯へのこだわり",
    category: "インタビュー",
    imageUrl: "/images/blog-bartender.jpg",
  },
  {
    id: 3,
    title: "一人飲みの愉しみ方、教えます",
    category: "コラム",
    imageUrl: "/images/blog-solobar.jpg",
  },
];

// 履歴がないときのサンプル
const FALLBACK_LAST_STORE = {
  name: `オリエンタルラウンジ ${DEFAULT_STORE_META.label}`,
  slug: DEFAULT_STORE_META.slug,
  maleRatio: "6",
  femaleRatio: "4",
  crowdLevel: "混雑度：70",
};


// --------------------------------------
// 簡易折れ線グラフ（SVG）
// --------------------------------------

function SimpleLineChart() {
  return (
    <svg
      viewBox="0 0 180 72"
      className="h-full w-full text-indigo-300"
      aria-hidden="true"
    >
      <polyline
        points="0,50 20,44 40,52 60,40 80,46 100,36 120,44 140,34 160,40 180,32"
        fill="none"
        stroke="currentColor"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <polyline
        points="0,60 20,56 40,62 60,52 80,58 100,48 120,56 140,46 160,52 180,44"
        fill="none"
        stroke="currentColor"
        strokeWidth={1.4}
        strokeLinecap="round"
        strokeLinejoin="round"
        className="opacity-60"
      />
    </svg>
  );
}

// --------------------------------------
// ヘルパー
// --------------------------------------


function getAreaLabelFromSlug(slug: string): string {
  return getStoreMetaBySlug(slug || DEFAULT_STORE).areaLabel || "Area unknown";
}

// --------------------------------------

// メインコンポーネント
// --------------------------------------

export default function HomePage() {
  const [lastStore, setLastStore] = useState<StoreMeta | null>(null);

  // 直近ひらいた店舗（localStorage）を読み込む
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

  const digestStores = useMemo(() => STORES.slice(0, 3), []);

  return (
    <div className="relative min-h-screen bg-black font-display text-slate-50">
      {/* 背景のぼかしグラデーション */}
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_20%_20%,rgba(79,70,229,0.18)_0%,transparent_32%),radial-gradient(circle_at_80%_70%,rgba(236,72,153,0.16)_0%,transparent_32%)]" />

      <div className="relative z-10">
        {/* コンテンツ本体 */}
        <main className="mx-auto flex max-w-6xl flex-col gap-10 px-4 py-6">
          {/* ヒーロー */}
          <section>
            <div className="relative overflow-hidden rounded-2xl border border-slate-800 bg-gradient-to-br from-slate-950 via-slate-900 to-black">
              <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_15%_20%,rgba(129,140,248,0.45)_0%,transparent_42%),radial-gradient(circle_at_80%_80%,rgba(248,113,113,0.4)_0%,transparent_42%)] opacity-80" />
              <div className="relative z-10 flex flex-col justify-center px-8 py-8 md:px-10 md:py-10">
                <p className="text-[11px] font-semibold tracking-[0.25em] text-indigo-200">
                  NIGHT MAP FOR ORIENTAL LOUNGE
                </p>
                <h1 className="mt-3 text-3xl font-bold leading-tight tracking-[-0.04em] md:text-4xl">
                  今夜の目的地を、
                  <br />
                  やさしく照らす案内灯。
                </h1>
                <p className="mt-4 max-w-xl text-sm text-slate-100/80">
                  オリエンタルラウンジを中心に、各店舗の男女比・混雑・予測をまとめてチェック。
                  「いま行くならどこ？」を、感覚ではなくデータで選べるようにします。
                </p>
                <div className="mt-5 flex flex-wrap gap-3 text-sm">
                  <Link
                    href="/stores"
                    className="inline-flex items-center justify-center rounded-md bg-indigo-500 px-4 py-2 font-semibold text-white shadow-sm shadow-black/40 hover:bg-indigo-400"
                  >
                    店舗一覧を見る
                  </Link>
                  <Link
                    href={`/store/${DEFAULT_STORE}?store=${DEFAULT_STORE}`}
                    className="inline-flex items-center justify-center rounded-md border border-slate-500/60 bg-black/40 px-4 py-2 text-slate-100/80 hover:border-amber-300/80 hover:bg-slate-900"
                  >
                    今夜の長崎店をチェック
                  </Link>
                </div>
              </div>
            </div>
          </section>

          {/* 前回の店舗 */}
                              <section className="space-y-3">
            <h2 className="text-sm font-semibold text-slate-100">Last visited store</h2>
            <div className="rounded-2xl border border-slate-800 bg-slate-950/80 px-4 py-4">
              <div className="grid gap-4 md:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)] md:items-center">
                <div>
                  {lastStore ? (
                    <>
                      <p className="text-[11px] text-slate-400">Last visited</p>
                      <p className="mt-1 text-lg font-semibold text-slate-50">
                        Oriental Lounge {lastStore.label}
                      </p>
                      <p className="mt-1 text-[11px] text-slate-400">
                        {lastStore.areaLabel}
                      </p>
                      <p className="mt-1 text-[11px] text-slate-400">
                        Gender ratio: pending / Crowd: pending
                      </p>
                      <p className="mt-2 text-[11px] text-slate-500">
                        When you open a store page, you can jump back here with one click.
                      </p>
                      <div className="mt-3">
                        <Link
                          href={`/store/${lastStore.slug}?store=${lastStore.slug}`}
                          className="inline-flex items-center justify-center rounded-md bg-indigo-500 px-3 py-1.5 text-xs font-semibold text-white hover:bg-indigo-400"
                        >
                          View details
                        </Link>
                      </div>
                    </>
                  ) : (
                    <>
                      <p className="text-[11px] text-slate-400">Sample store</p>
                      <p className="mt-1 text-lg font-semibold text-slate-50">
                        {FALLBACK_LAST_STORE.name}
                      </p>
                      <p className="mt-1 text-[11px] text-slate-400">
                        Gender ratio: {FALLBACK_LAST_STORE.maleRatio}:{FALLBACK_LAST_STORE.femaleRatio} / {FALLBACK_LAST_STORE.crowdLevel}
                      </p>
                      <p className="mt-2 text-[11px] text-slate-500">
                        When you open a store page, you can jump back here with one click.
                      </p>
                      <div className="mt-3">
                        <Link
                          href="/stores"
                          className="inline-flex items-center justify-center rounded-md bg-indigo-500 px-3 py-1.5 text-xs font-semibold text-white hover:bg-indigo-400"
                        >
                          Browse all stores
                        </Link>
                      </div>
                    </>
                  )}
                </div>
                <div className="h-28 w-full overflow-hidden rounded-xl border border-slate-800 bg-slate-950 p-2">
                  <SimpleLineChart />
                </div>
              </div>
            </div>
          </section>

          {/* 近くの店舗（ダミー） */}
          <section className="space-y-3">
            <h2 className="text-sm font-semibold text-slate-100">近くの店舗</h2>
            <div className="grid gap-3 md:grid-cols-3">
              {NEAR_STORES.map((s) => (
                <div
                  key={s.id}
                  className="flex flex-col rounded-2xl border border-slate-800 bg-slate-950/80 p-3 text-sm transition hover:border-amber-400/80 hover:bg-slate-900 hover:shadow-[0_0_20px_rgba(251,191,36,0.25)]"
                >
                  <div className="h-16 w-full overflow-hidden rounded-md border border-slate-800 bg-slate-950 p-2">
                    <SimpleLineChart />
                  </div>
                  <p className="mt-2 text-sm font-semibold text-slate-50">
                    {s.name}
                  </p>
                  <p className="mt-1 text-[11px] text-slate-400">
                    男女比：{s.maleRatio}：{s.femaleRatio}
                  </p>
                  <div className="mt-2 flex flex-wrap gap-1">
                    {s.tags.map((tag) => (
                      <span
                        key={tag}
                        className="rounded-full bg-slate-800 px-2 py-0.5 text-[10px] text-slate-200"
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </section>

          {/* 今夜のおすすめ（ダミー） */}
          <section className="space-y-3">
            <h2 className="text-sm font-semibold text-slate-100">
              今夜のおすすめ（東京都）
            </h2>
            <div className="grid gap-3 md:grid-cols-3">
              {FEATURED_STORES.map((s) => (
                <div
                  key={s.id}
                  className="flex flex-col rounded-2xl border border-slate-800 bg-slate-950/90 p-3 text-sm transition hover:border-amber-400/80 hover:bg-slate-900 hover:shadow-[0_0_20px_rgba(251,191,36,0.25)]"
                >
                  <div className="flex items-center justify-between">
                    <span className="inline-flex items-center rounded-full bg-indigo-500/80 px-2.5 py-0.5 text-[11px] font-semibold text-white">
                      {s.rank}位
                    </span>
                    <span className="text-[11px] text-slate-400">
                      おすすめ度 {s.recommendScore}
                    </span>
                  </div>
                  <p className="mt-2 text-sm font-semibold text-slate-50">
                    {s.name}
                  </p>
                  <p className="mt-1 text-[11px] text-slate-400">エリア：{s.area}</p>
                  <p className="mt-1 text-[11px] text-slate-400">
                    混雑傾向：{s.crowdLevel}
                  </p>
                  <p className="mt-1 text-[11px] text-slate-400">
                    ピーク予測時刻：{s.peakTime}
                  </p>
                  <div className="mt-2 h-16 w-full overflow-hidden rounded-md border border-slate-800 bg-slate-950 p-2">
                    <SimpleLineChart />
                  </div>
                </div>
              ))}
            </div>
          </section>

          {/* 店舗一覧ダイジェスト（StoreCard 利用） */}
          <section className="space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold text-slate-100">
                店舗一覧（ダイジェスト）
              </h2>
              <Link
                href="/stores"
                className="text-xs text-indigo-300 hover:text-indigo-200"
              >
                すべて見る →
              </Link>
            </div>
                        <div className="grid gap-3 md:grid-cols-3">
              {digestStores.map((store, idx) => (
                <StoreCard
                  key={store.slug}
                  slug={store.slug}
                  label={`Oriental Lounge ${store.label}`}
                  brandLabel="ORIENTAL LOUNGE"
                  areaLabel={store.areaLabel}
                  isHighlight={idx === 0}
                  stats={{
                    genderRatio: "pending",
                    crowdLevel: "pending",
                    recommendLabel: "pending",
                  }}
                />
              ))}
            </div>
          </section>

          {/* ブログ新着記事 */}
          <section className="space-y-3">
            <h2 className="text-sm font-semibold text-slate-100">
              ブログ新着記事
            </h2>
            <div className="grid gap-4 md:grid-cols-3">
              {BLOG_ARTICLES.map((article) => (
                <Link
                  key={article.id}
                  href="/blog"
                  className="flex flex-col overflow-hidden rounded-2xl border border-slate-800 bg-slate-950/80 text-sm transition hover:border-amber-400/80 hover:bg-slate-900 hover:shadow-[0_0_20px_rgba(251,191,36,0.25)]"
                >
                  <div
                    className="h-32 w-full bg-cover bg-center"
                    style={{ backgroundImage: `url(${article.imageUrl})` }}
                  />
                  <div className="flex flex-1 flex-col p-3">
                    <p className="text-[11px] text-indigo-200">
                      {article.category}
                    </p>
                    <p className="mt-1 text-sm font-semibold leading-snug text-slate-50">
                      {article.title}
                    </p>
                  </div>
                </Link>
              ))}
            </div>
          </section>

          {/* めぐりびとは */}
          <section className="space-y-3">
            <h2 className="text-sm font-semibold text-slate-100">めぐりびとは</h2>
            <div className="rounded-2xl border border-slate-800 bg-slate-950/80 p-4 text-sm text-slate-100/80">
              <p>
                「めぐりび」は、特別な夜にふさわしい一軒を求めるあなたのための案内灯です。
                リアルタイムの混雑傾向や男女比、独自の予測モデルをもとに、「いま行くならどこが良さそうか」をやさしく教えてくれます。
              </p>
              <p className="mt-2">
                まずはオリエンタルラウンジから対応を始め、今後は他ブランドや二次会スポットにも対応していく予定です。
              </p>
            </div>
          </section>
        </main>

        {/* フッター */}
        <footer className="mx-auto mt-4 max-w-6xl border-t border-slate-800 px-4 pt-4 text-[11px] text-slate-500">
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
              <Link href="/about" className="hover:text-slate-300">
                運営情報
              </Link>
            </div>
            <p className="text-slate-600">© めぐりび All Rights Reserved.</p>
          </div>
        </footer>
      </div>
    </div>
  );
}
