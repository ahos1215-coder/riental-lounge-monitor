"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  clearFavoriteStores,
  clearStoreHistory,
  getFavoriteStoreSlugs,
  getStoreHistorySlugs,
  removeFavoriteStore,
} from "@/lib/browser/meguribiStorage";
import { getStoreMetaBySlug, type StoreMeta } from "@/app/config/stores";
import {
  STORE_CARD_RANGE_LIMIT,
  STORE_CARD_SPARKLINE_POINTS,
  buildGenderSparklineFromRange,
  parseRangeResponse,
  pickLatestRangeRow,
} from "@/lib/storeCardRangeSparkline";

type MegribiScoreItem = {
  slug: string;
  score: number;
  total: number;
  men: number;
  women: number;
  female_ratio: number;
};

type FavCardData = {
  slug: string;
  meta: StoreMeta;
  men: number;
  women: number;
  total: number;
  genderRatio: string;
  sparklineMen: number[];
  sparklineWomen: number[];
  megribiScore: number | null;
  forecastPeak: string;
  forecastCalm: string;
  forecastMaxPred: number;
};

function GenderTrendMini({ men, women }: { men: number[]; women: number[] }) {
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
    <svg viewBox="0 0 180 50" className="h-10 w-full" aria-hidden>
      <line x1="0" y1="48" x2="180" y2="48" className="stroke-white/[0.06]" strokeWidth={1} />
      <polyline points={pathMen} fill="none" className="stroke-cyan-300/80" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
      <polyline points={pathWomen} fill="none" className="stroke-pink-300/80" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function ScoreBadge({ score }: { score: number | null }) {
  if (score === null) return null;
  const pct = Math.round(score * 100);
  const color = pct >= 70 ? "text-emerald-300 border-emerald-400/40 bg-emerald-500/10" : pct >= 40 ? "text-amber-300 border-amber-400/40 bg-amber-500/10" : "text-slate-400 border-slate-500/30 bg-slate-500/10";
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-bold ${color}`}>
      スコア {pct}
    </span>
  );
}

function FavCardSkeleton() {
  return (
    <div className="h-44 animate-pulse rounded-2xl border border-slate-800 bg-slate-900/40" />
  );
}

export default function MyPageClient() {
  const [historySlugs, setHistorySlugs] = useState<string[]>([]);
  const [favoriteSlugs, setFavoriteSlugs] = useState<string[]>([]);
  const [favCards, setFavCards] = useState<FavCardData[]>([]);
  const [favLoading, setFavLoading] = useState(false);

  const refresh = useCallback(() => {
    setHistorySlugs(getStoreHistorySlugs());
    setFavoriteSlugs(getFavoriteStoreSlugs());
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  useEffect(() => {
    let mounted = true;
    const targets = favoriteSlugs.slice(0, 8);
    if (!targets.length) { setFavCards([]); return; }

    setFavLoading(true);

    (async () => {
      const fmt = (iso: string) => {
        try {
          return new Intl.DateTimeFormat("ja-JP", {
            timeZone: "Asia/Tokyo", hour: "2-digit", minute: "2-digit", hour12: false,
          }).format(new Date(iso));
        } catch { return "--:--"; }
      };

      let megribiMap: Record<string, MegribiScoreItem> = {};
      try {
        const slugsCsv = targets.join(",");
        const mRes = await fetch(`/api/megribi_score?stores=${encodeURIComponent(slugsCsv)}`);
        if (mRes.ok) {
          const mJson = (await mRes.json()) as { ok: boolean; data?: MegribiScoreItem[] };
          if (mJson.ok && Array.isArray(mJson.data)) {
            for (const item of mJson.data) megribiMap[item.slug] = item;
          }
        }
      } catch { /* ignore */ }

      const cards = await Promise.all(
        targets.map(async (slug): Promise<FavCardData> => {
          const meta = getStoreMetaBySlug(slug);
          const base: FavCardData = {
            slug, meta, men: 0, women: 0, total: 0, genderRatio: "—",
            sparklineMen: [], sparklineWomen: [],
            megribiScore: megribiMap[slug]?.score ?? null,
            forecastPeak: "--:--", forecastCalm: "--:--", forecastMaxPred: 0,
          };

          const [rangeResult, forecastResult] = await Promise.allSettled([
            fetch(`/api/range?store=${encodeURIComponent(slug)}&limit=${STORE_CARD_RANGE_LIMIT}`),
            fetch(`/api/forecast_today?store=${encodeURIComponent(slug)}`),
          ]);

          if (rangeResult.status === "fulfilled" && rangeResult.value.ok) {
            try {
              const rangeBody: unknown = await rangeResult.value.json();
              const rangeRows = parseRangeResponse(rangeBody);
              const current = pickLatestRangeRow(rangeRows) ?? {};
              const menNow = Math.max(0, Math.round(Number(current.men ?? 0)));
              const womenNow = Math.max(0, Math.round(Number(current.women ?? 0)));
              base.men = menNow;
              base.women = womenNow;
              base.total = Math.max(0, Math.round(Number(current.total ?? menNow + womenNow)));
              base.genderRatio = `${menNow}:${womenNow}`;
              const gs = buildGenderSparklineFromRange(rangeRows, STORE_CARD_SPARKLINE_POINTS);
              base.sparklineMen = gs.men;
              base.sparklineWomen = gs.women;
            } catch { /* ignore */ }
          }

          if (forecastResult.status === "fulfilled" && forecastResult.value.ok) {
            try {
              const fb = (await forecastResult.value.json()) as { data?: Array<{ ts: string; total_pred?: number }> };
              const data = Array.isArray(fb?.data) ? fb.data : [];
              if (data.length) {
                let peak = data[0];
                let calm = data[0];
                for (const p of data) {
                  const v = Number(p.total_pred ?? 0);
                  if (v > Number(peak.total_pred ?? 0)) peak = p;
                  if (v < Number(calm.total_pred ?? 0)) calm = p;
                }
                base.forecastPeak = fmt(peak.ts);
                base.forecastCalm = fmt(calm.ts);
                base.forecastMaxPred = Math.round(Number(peak.total_pred ?? 0));
              }
            } catch { /* ignore */ }
          }

          return base;
        }),
      );

      if (mounted) {
        setFavCards(cards);
        setFavLoading(false);
      }
    })();

    return () => { mounted = false; };
  }, [favoriteSlugs]);

  const historyMetas = useMemo(
    () => historySlugs.map((slug) => ({ slug, meta: getStoreMetaBySlug(slug) })),
    [historySlugs],
  );

  return (
    <main className="relative min-h-[calc(100vh-80px)] bg-black font-display text-white">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_20%_20%,rgba(79,70,229,0.10)_0%,transparent_30%)]" />

      <div className="relative z-10 mx-auto w-full max-w-4xl px-4 pb-16 pt-10">
        {/* Header */}
        <div className="flex items-end justify-between gap-3">
          <div>
            <h1 className="text-2xl font-black tracking-tight md:text-3xl">マイページ</h1>
            <p className="mt-1 text-xs text-white/50">
              閲覧履歴・お気に入りはこのブラウザにだけ保存されます。
            </p>
          </div>
          <Link href="/" className="text-xs text-white/40 hover:text-white">← トップへ</Link>
        </div>

        {/* Quick navigation */}
        <nav className="mt-6 flex flex-wrap gap-2">
          {[
            { href: "/stores", label: "店舗一覧" },
            { href: "/reports", label: "AI予測レポート" },
            { href: "/blog", label: "ブログ" },
            { href: "/reports?tab=weekly", label: "週次 Insights" },
          ].map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className="rounded-full border border-white/15 bg-white/5 px-3 py-1.5 text-xs font-medium text-white/80 transition hover:border-indigo-400/50 hover:text-indigo-200"
            >
              {link.label}
            </Link>
          ))}
        </nav>

        {/* Favorites section */}
        <section className="mt-10 space-y-4">
          <div className="flex items-center justify-between gap-2">
            <h2 className="text-sm font-bold text-white/90">
              お気に入り店舗
              {favoriteSlugs.length > 0 && (
                <span className="ml-2 text-[11px] font-normal text-white/40">{favoriteSlugs.length}件</span>
              )}
            </h2>
            {favoriteSlugs.length > 0 && (
              <button
                type="button"
                onClick={() => { clearFavoriteStores(); refresh(); }}
                className="text-[11px] text-white/40 hover:text-rose-300"
              >
                すべて解除
              </button>
            )}
          </div>

          {favoriteSlugs.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-white/15 bg-white/[0.02] p-6 text-center">
              <p className="text-sm text-white/50">店舗ページの「お気に入りに追加」から登録できます。</p>
              <Link
                href="/stores"
                className="mt-3 inline-block rounded-full border border-indigo-400/30 bg-indigo-500/10 px-4 py-1.5 text-xs font-medium text-indigo-200 hover:bg-indigo-500/20"
              >
                店舗一覧を見る →
              </Link>
            </div>
          ) : favLoading ? (
            <div className="grid gap-3 sm:grid-cols-2">
              {favoriteSlugs.slice(0, 8).map((s) => <FavCardSkeleton key={s} />)}
            </div>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2">
              {favCards.map((card) => (
                <div
                  key={card.slug}
                  className="group relative flex flex-col rounded-2xl border border-slate-800 bg-slate-950/80 p-4 transition hover:border-indigo-500/40"
                >
                  {/* Remove button */}
                  <button
                    type="button"
                    onClick={(e) => { e.stopPropagation(); removeFavoriteStore(card.slug); refresh(); }}
                    className="absolute right-3 top-3 rounded-md border border-white/10 px-1.5 py-0.5 text-[10px] text-white/30 transition hover:border-rose-400/40 hover:text-rose-300"
                    aria-label={`${card.meta.label} をお気に入りから外す`}
                  >
                    ✕
                  </button>

                  {/* Store info + score */}
                  <div className="flex items-start justify-between gap-2 pr-8">
                    <div>
                      <Link
                        href={`/store/${card.slug}?store=${card.slug}`}
                        className="text-sm font-bold text-white group-hover:text-indigo-200"
                      >
                        {card.meta.label}
                      </Link>
                      <p className="text-[11px] text-white/40">{card.meta.areaLabel}</p>
                    </div>
                    <ScoreBadge score={card.megribiScore} />
                  </div>

                  {/* Realtime numbers */}
                  <div className="mt-3 flex items-center gap-2 text-[11px]">
                    <span className="rounded-full border border-cyan-400/30 bg-cyan-500/10 px-2 py-0.5 font-semibold text-cyan-200">
                      男性 {card.men}
                    </span>
                    <span className="rounded-full border border-pink-400/30 bg-pink-500/10 px-2 py-0.5 font-semibold text-pink-200">
                      女性 {card.women}
                    </span>
                    <span className="text-white/40">計 {card.total}</span>
                  </div>

                  {/* Sparkline */}
                  {card.sparklineMen.length >= 2 && card.sparklineWomen.length >= 2 && (
                    <div className="mt-2 overflow-hidden rounded-md border border-slate-800 bg-slate-950 px-2 py-1">
                      <GenderTrendMini men={card.sparklineMen} women={card.sparklineWomen} />
                      <div className="flex justify-center gap-3 text-[9px] text-white/35">
                        <span className="flex items-center gap-1">
                          <span className="h-0.5 w-2 rounded-full bg-cyan-300/80" aria-hidden /> 男性
                        </span>
                        <span className="flex items-center gap-1">
                          <span className="h-0.5 w-2 rounded-full bg-pink-300/80" aria-hidden /> 女性
                        </span>
                      </div>
                    </div>
                  )}

                  {/* Forecast row */}
                  {card.forecastMaxPred > 0 && (
                    <div className="mt-2 flex items-center gap-3 text-[10px] text-white/50">
                      <span>ピーク <strong className="text-white/70">{card.forecastPeak}</strong></span>
                      <span>落ち着き <strong className="text-white/70">{card.forecastCalm}</strong></span>
                      <span>最大 <strong className="text-white/70">{card.forecastMaxPred}人</strong></span>
                    </div>
                  )}

                  {/* Action links */}
                  <div className="mt-auto flex gap-3 pt-3 text-[11px]">
                    <Link
                      href={`/store/${card.slug}?store=${card.slug}`}
                      className="font-medium text-indigo-300 hover:text-indigo-200"
                    >
                      店舗詳細 →
                    </Link>
                    <Link
                      href={`/reports/daily/${encodeURIComponent(card.slug)}`}
                      className="text-white/40 hover:text-white/70"
                    >
                      Daily
                    </Link>
                    <Link
                      href={`/reports/weekly/${encodeURIComponent(card.slug)}`}
                      className="text-white/40 hover:text-white/70"
                    >
                      Weekly
                    </Link>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* History section */}
        <section className="mt-10 space-y-3">
          <div className="flex items-center justify-between gap-2">
            <h2 className="text-sm font-bold text-white/90">
              最近見た店舗
              {historySlugs.length > 0 && (
                <span className="ml-2 text-[11px] font-normal text-white/40">{historySlugs.length}件</span>
              )}
            </h2>
            {historySlugs.length > 0 && (
              <button
                type="button"
                onClick={() => { clearStoreHistory(); refresh(); }}
                className="text-[11px] text-white/40 hover:text-rose-300"
              >
                履歴を消す
              </button>
            )}
          </div>

          {historySlugs.length === 0 ? (
            <p className="rounded-2xl border border-dashed border-white/15 bg-white/[0.02] p-4 text-center text-sm text-white/45">
              店舗ページを開くと、ここに最大12件まで表示されます。
            </p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {historyMetas.map(({ slug, meta }) => (
                <Link
                  key={slug}
                  href={`/store/${slug}?store=${slug}`}
                  className="rounded-full border border-white/10 bg-white/[0.04] px-3 py-1.5 text-xs text-white/70 transition hover:border-indigo-400/30 hover:text-indigo-200"
                >
                  {meta.label}
                  <span className="ml-1 text-[10px] text-white/30">{meta.areaLabel}</span>
                </Link>
              ))}
            </div>
          )}
        </section>

        {/* Info footer */}
        <section className="mt-10 rounded-2xl border border-slate-800 bg-slate-950/60 p-4 text-xs text-white/45">
          <p className="font-medium text-white/60">データについて</p>
          <ul className="mt-2 space-y-1 pl-4 list-disc">
            <li>お気に入り・履歴はこの端末の localStorage に保存されます（ログイン不要）</li>
            <li>めぐりびスコアは混雑率 × 女性比率から算出した参考指標です</li>
            <li>予測値は ML モデルの参考推計であり、実際の来客を保証するものではありません</li>
          </ul>
        </section>
      </div>
    </main>
  );
}
