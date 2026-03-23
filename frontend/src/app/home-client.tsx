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
import { LAST_STORE_KEY } from "@/lib/browser/meguribiStorage";

export type HomeBlogTeaser = {
  slug: string;
  title: string;
  categoryLabel: string;
  dateLabel: string;
};

type HomePageProps = {
  latestBlogPosts: HomeBlogTeaser[];
};

// 履歴がないときのサンプル（数値ダミーは出さない）
const FALLBACK_LAST_STORE = {
  name: `オリエンタルラウンジ ${getStoreMetaBySlug(DEFAULT_STORE).label}`,
  slug: getStoreMetaBySlug(DEFAULT_STORE).slug,
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
  return getStoreMetaBySlug(slug || DEFAULT_STORE).areaLabel || "エリア未設定";
}

// --------------------------------------
// メインコンポーネント
// --------------------------------------

export default function HomePage({ latestBlogPosts }: HomePageProps) {
  const [lastStore, setLastStore] = useState<StoreMeta | null>(null);

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

  /** 掲載店舗ダイジェスト（stores.ts ベース、stats は省略で「準備中」） */
  const digestStores = useMemo(() => STORES.slice(0, 6), []);

  return (
    <div className="relative min-h-screen bg-black font-display text-slate-50">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_20%_20%,rgba(79,70,229,0.18)_0%,transparent_32%),radial-gradient(circle_at_80%_70%,rgba(236,72,153,0.16)_0%,transparent_32%)]" />

      <div className="relative z-10">
        <main className="mx-auto flex max-w-6xl flex-col gap-10 px-4 py-6">
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
                        男女比・混雑・おすすめは店舗ページでご確認ください。
                      </p>
                      <p className="mt-2 text-[11px] text-slate-500">
                        店舗ページを開くと、あとからここへワンタップで戻れます。
                      </p>
                      <div className="mt-3">
                        <Link
                          href={`/store/${lastStore.slug}?store=${lastStore.slug}`}
                          className="inline-flex items-center justify-center rounded-md bg-indigo-500 px-3 py-1.5 text-xs font-semibold text-white hover:bg-indigo-400"
                        >
                          店舗ページへ
                        </Link>
                      </div>
                    </>
                  ) : (
                    <>
                      <p className="text-[11px] text-slate-400">サンプル</p>
                      <p className="mt-1 text-lg font-semibold text-slate-50">
                        {FALLBACK_LAST_STORE.name}
                      </p>
                      <p className="mt-1 text-[11px] text-slate-400">
                        {getAreaLabelFromSlug(FALLBACK_LAST_STORE.slug)}
                      </p>
                      <p className="mt-1 text-[11px] text-slate-400">
                        店舗を開くと、男女比・混雑などをまとめて表示します。
                      </p>
                      <p className="mt-2 text-[11px] text-slate-500">
                        店舗ページを開くと、あとからここへワンタップで戻れます。
                      </p>
                      <div className="mt-3">
                        <Link
                          href="/stores"
                          className="inline-flex items-center justify-center rounded-md bg-indigo-500 px-3 py-1.5 text-xs font-semibold text-white hover:bg-indigo-400"
                        >
                          店舗一覧へ
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

          <section className="space-y-3">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h2 className="text-sm font-semibold text-slate-100">掲載中の店舗</h2>
                <p className="mt-0.5 text-[11px] text-slate-500">
                  オリエンタルラウンジ（config の店舗一覧ベース）。詳細は各店舗ページへ。
                </p>
              </div>
              <Link
                href="/stores"
                className="shrink-0 text-xs text-indigo-300 hover:text-indigo-200"
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
                />
              ))}
            </div>
          </section>

          <section className="space-y-3">
            <div className="flex flex-wrap items-end justify-between gap-3">
              <h2 className="text-sm font-semibold text-slate-100">ブログ新着</h2>
              <Link href="/blog" className="text-xs text-indigo-300 hover:text-indigo-200">
                記事一覧へ →
              </Link>
            </div>
            {latestBlogPosts.length === 0 ? (
              <div className="rounded-2xl border border-slate-800 bg-slate-950/80 p-4 text-sm text-slate-400">
                記事を準備中です。しばらくしてから
                <Link href="/blog" className="text-indigo-300 hover:text-indigo-200">
                  ブログ一覧
                </Link>
                をご覧ください。
              </div>
            ) : (
              <div className="grid gap-4 md:grid-cols-3">
                {latestBlogPosts.map((article) => (
                  <Link
                    key={article.slug}
                    href={`/blog/${article.slug}`}
                    className="flex flex-col overflow-hidden rounded-2xl border border-slate-800 bg-slate-950/80 text-sm transition hover:border-amber-400/80 hover:bg-slate-900 hover:shadow-[0_0_20px_rgba(251,191,36,0.25)]"
                  >
                    <div className="flex h-24 items-center justify-center border-b border-slate-800 bg-gradient-to-br from-indigo-900/40 to-slate-900/80">
                      <span className="text-[11px] font-medium text-indigo-200/90">
                        {article.categoryLabel}
                      </span>
                    </div>
                    <div className="flex flex-1 flex-col p-3">
                      <p className="text-[10px] text-slate-500">{article.dateLabel}</p>
                      <p className="mt-1 text-sm font-semibold leading-snug text-slate-50">
                        {article.title}
                      </p>
                    </div>
                  </Link>
                ))}
              </div>
            )}
          </section>

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
