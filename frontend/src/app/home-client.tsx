"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  DEFAULT_STORE,
  STORES,
  getStoreMetaBySlug,
  type StoreMeta,
} from "./config/stores";
import { LAST_STORE_KEY } from "@/lib/browser/meguribiStorage";
import {
  STORE_CARD_RANGE_LIMIT,
  STORE_CARD_SPARKLINE_POINTS,
  buildActualSparklineFromRange,
  buildGenderSparklineFromRange,
  parseRangeResponse,
} from "@/lib/storeCardRangeSparkline";

export type HomeBlogTeaser = {
  slug: string;
  title: string;
  categoryLabel: string;
  dateLabel: string;
};

type HomePageProps = {
  latestBlogPosts: HomeBlogTeaser[];
};

const FALLBACK_LAST_STORE = {
  name: `オリエンタルラウンジ ${getStoreMetaBySlug(DEFAULT_STORE).label}`,
  slug: getStoreMetaBySlug(DEFAULT_STORE).slug,
};

function LastVisitChartSkeleton() {
  return (
    <div
      className="flex h-28 w-full animate-pulse flex-col justify-end rounded-xl border border-slate-800 bg-slate-900/40 p-3"
      aria-hidden
    >
      <div className="h-16 w-full rounded-md bg-slate-800/70" />
      <div className="mt-2 flex justify-center gap-3">
        <div className="h-2 w-10 rounded bg-slate-800/70" />
        <div className="h-2 w-10 rounded bg-slate-800/70" />
      </div>
    </div>
  );
}

/** StoreCard と同系の男女ミニチャート（実測レンジ） */
function LastVisitGenderTrendChart({ men, women }: { men: number[]; women: number[] }) {
  const all = [...men, ...women];
  const max = Math.max(...all, 1);
  const min = Math.min(...all);
  const span = Math.max(1, max - min);
  const width = 180;
  const n = men.length;
  const step = width / Math.max(1, n - 1);
  const toY = (v: number) => Math.round(44 - ((v - min) / span) * 28);
  const pathMen = men.map((v, i) => `${Math.round(i * step)},${toY(v)}`).join(" ");
  const pathWomen = women.map((v, i) => `${Math.round(i * step)},${toY(v)}`).join(" ");

  return (
    <div className="flex w-full flex-col gap-0.5">
      <svg
        viewBox="0 0 180 56"
        className="h-24 w-full shrink-0"
        role="img"
        aria-label="直近の男性・女性人数の推移（実測）"
      >
        <line x1="0" y1="50" x2="180" y2="50" className="stroke-white/[0.08]" strokeWidth={1} />
        <polyline
          points={pathMen}
          fill="none"
          className="stroke-cyan-300/90"
          strokeWidth={2}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <polyline
          points={pathWomen}
          fill="none"
          className="stroke-pink-300/90"
          strokeWidth={2}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      <div className="flex justify-center gap-3 text-[9px] leading-none text-white/40">
        <span className="flex items-center gap-1">
          <span className="h-0.5 w-2.5 rounded-full bg-cyan-300/90" aria-hidden />
          男性
        </span>
        <span className="flex items-center gap-1">
          <span className="h-0.5 w-2.5 rounded-full bg-pink-300/90" aria-hidden />
          女性
        </span>
        <span className="text-white/30">実測・直近</span>
      </div>
    </div>
  );
}

function LastVisitTotalTrendChart({ points }: { points: number[] }) {
  const max = Math.max(...points);
  const min = Math.min(...points);
  const span = Math.max(1, max - min);
  const step = 180 / Math.max(1, points.length - 1);
  const path = points
    .map((v, i) => {
      const x = Math.round(i * step);
      const y = Math.round(56 - ((v - min) / span) * 40);
      return `${x},${y}`;
    })
    .join(" ");

  return (
    <svg
      viewBox="0 0 180 64"
      className="h-24 w-full text-indigo-400/85"
      role="img"
      aria-label="直近の人数推移（実測・合計）"
    >
      <polyline
        points={path}
        fill="none"
        stroke="currentColor"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function getAreaLabelFromSlug(slug: string): string {
  return getStoreMetaBySlug(slug || DEFAULT_STORE).areaLabel || "エリア未設定";
}

type LastVisitFetchedTrend = {
  loading: boolean;
  men: number[];
  women: number[];
  fallbackLine?: number[];
};

export default function HomePage({ latestBlogPosts }: HomePageProps) {
  const [lastStore, setLastStore] = useState<StoreMeta | null>(null);
  const [lastVisitFetched, setLastVisitFetched] = useState<LastVisitFetchedTrend>({
    loading: true,
    men: [],
    women: [],
  });

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
          <section>
            <div className="relative overflow-hidden rounded-2xl border border-slate-800 bg-gradient-to-br from-slate-950 via-slate-900 to-black">
              <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_15%_20%,rgba(129,140,248,0.45)_0%,transparent_42%),radial-gradient(circle_at_80%_80%,rgba(248,113,113,0.4)_0%,transparent_42%)] opacity-80" />
              <div className="relative z-10 flex flex-col justify-center px-8 py-8 md:px-10 md:py-10">
                <p className="text-[11px] font-semibold tracking-[0.25em] text-indigo-200">
                  NIGHT MAP FOR ORIENTAL LOUNGE
                </p>
                <h1 className="mt-3 text-3xl font-bold leading-tight tracking-[-0.04em] md:text-4xl">
                  今夜の一軒を、
                  <br />
                  やさしく照らす案内灯。
                </h1>
                <p className="mt-4 max-w-xl text-sm text-slate-100/80">
                  オリエンタルラウンジを中心に、各店舗の男女比や混雑の予測をまとめてチェック。
                  「いま行くならどこ？」を、感覚ではなくデータで選べるようにします。
                </p>
                <div className="mt-5 flex flex-wrap gap-3 text-sm">
                  <Link
                    href="/stores"
                    className="inline-flex items-center justify-center rounded-md bg-indigo-500 px-4 py-2 font-semibold text-white shadow-sm shadow-black/40 hover:bg-indigo-400"
                  >
                    今夜の予測を見る
                  </Link>
                  <Link
                    href="#store-directory"
                    className="inline-flex items-center justify-center rounded-md border border-slate-500/60 bg-black/40 px-4 py-2 text-slate-100/80 hover:border-amber-300/80 hover:bg-slate-900"
                  >
                    店舗一覧の案内へ
                  </Link>
                </div>
                <nav
                  className="mt-4 flex flex-wrap gap-x-5 gap-y-2 border-t border-white/10 pt-4 text-xs"
                  aria-label="主要ページへのショートカット"
                >
                  <Link href="/stores" className="text-indigo-300 hover:text-indigo-200">
                    店舗一覧
                  </Link>
                  <Link
                    href="/insights/weekly"
                    className="text-indigo-300 hover:text-indigo-200"
                  >
                    週次 Insights
                  </Link>
                  <Link href="/blog" className="text-indigo-300 hover:text-indigo-200">
                    ブログ
                  </Link>
                  <Link href="/mypage" className="text-indigo-300 hover:text-indigo-200">
                    マイページ
                  </Link>
                </nav>
                <p className="mt-3 max-w-2xl text-[11px] leading-relaxed text-slate-400">
                  表示は参考情報です。実測は取得タイミングにより遅れる場合があります。予測はモデルによる推定であり、実際の混雑や席状況とは異なることがあります。
                </p>
              </div>
            </div>
          </section>

          <section id="last-visited" className="scroll-mt-24 space-y-3">
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
                <div className="min-h-28 w-full overflow-hidden rounded-xl border border-slate-800 bg-slate-950 p-2">
                  {lastVisitChartBlock}
                </div>
              </div>
            </div>
          </section>

          <section id="store-directory" className="scroll-mt-24 space-y-3">
            <h2 className="text-sm font-semibold text-slate-100">店舗の男女比・予測を見る</h2>
            <div className="rounded-2xl border border-slate-800 bg-slate-950/80 p-4 text-sm leading-relaxed text-slate-100/85">
              <p>
                オリエンタルラウンジ{" "}
                <span className="font-semibold text-slate-100">{STORES.length}</span>{" "}
                店舗の実測・予測は、
                <strong className="font-medium text-indigo-200">店舗一覧</strong>
                にまとめています。地域での絞り込み・検索・ページ送りで探せます。
              </p>
              <p className="mt-2 text-[13px] text-slate-400">
                トップでは「直前に見た店」の推移だけを表示し、特定店の抜粋一覧は出しません（一覧と役割が重なるため）。
              </p>
              <div className="mt-4">
                <Link
                  href="/stores"
                  className="inline-flex items-center justify-center rounded-md bg-indigo-500 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-400"
                >
                  店舗一覧を開く
                </Link>
              </div>
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
                    <div className="flex min-h-24 flex-wrap items-center justify-center gap-2 border-b border-slate-800 bg-gradient-to-br from-indigo-900/40 to-slate-900/80 px-3 py-3">
                      <span className="text-center text-[11px] font-medium text-indigo-200/90">
                        {article.categoryLabel}
                      </span>
                      <span className="rounded-full border border-emerald-400/50 bg-emerald-500/10 px-2 py-0.5 text-[10px] text-emerald-200">
                        予測ベース
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
            <div className="rounded-2xl border border-slate-800 bg-slate-950/80 p-4 text-sm leading-relaxed text-slate-100/80">
              <p>
                「めぐりび」は、特別な夜にふさわしい一軒を探すための案内灯です。
                混雑の傾向や男女比、独自の予測モデルをもとに、「いま行くならどこが良さそうか」の参考をお届けします。
              </p>
              <p className="mt-2">
                まずはオリエンタルラウンジから対応し、今後は他ブランドや二次会スポットにも広げていく予定です。
              </p>
            </div>
          </section>
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
