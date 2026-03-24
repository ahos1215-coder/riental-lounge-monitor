"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import {
  clearFavoriteStores,
  clearStoreHistory,
  getFavoriteStoreSlugs,
  getStoreHistorySlugs,
  removeFavoriteStore,
} from "@/lib/browser/meguribiStorage";
import { getStoreMetaBySlug, type StoreMeta } from "@/app/config/stores";

function slugToMeta(slug: string): StoreMeta {
  return getStoreMetaBySlug(slug);
}

export default function MyPageClient() {
  const [historySlugs, setHistorySlugs] = useState<string[]>([]);
  const [favoriteSlugs, setFavoriteSlugs] = useState<string[]>([]);
  const [quickForecast, setQuickForecast] = useState<
    Array<{ slug: string; peak: string; calm: string; maxPred: number }>
  >([]);

  const refresh = useCallback(() => {
    setHistorySlugs(getStoreHistorySlugs());
    setFavoriteSlugs(getFavoriteStoreSlugs());
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    let mounted = true;
    const targets = favoriteSlugs.slice(0, 6);
    if (!targets.length) {
      setQuickForecast([]);
      return;
    }
    (async () => {
      const fmt = (iso: string) =>
        new Intl.DateTimeFormat("ja-JP", {
          timeZone: "Asia/Tokyo",
          hour: "2-digit",
          minute: "2-digit",
          hour12: false,
        }).format(new Date(iso));
      const rows = await Promise.all(
        targets.map(async (slug) => {
          try {
            const res = await fetch(`/api/forecast_today?store=${encodeURIComponent(slug)}`, {
              cache: "no-store",
            });
            const body = (await res.json()) as { data?: Array<{ ts: string; total_pred?: number }> };
            const data = Array.isArray(body?.data) ? body.data : [];
            if (!data.length) return { slug, peak: "--:--", calm: "--:--", maxPred: 0 };
            let peak = data[0];
            let calm = data[0];
            for (const p of data) {
              const v = Number(p.total_pred ?? 0);
              if (v > Number(peak.total_pred ?? 0)) peak = p;
              if (v < Number(calm.total_pred ?? 0)) calm = p;
            }
            return {
              slug,
              peak: fmt(peak.ts),
              calm: fmt(calm.ts),
              maxPred: Math.round(Number(peak.total_pred ?? 0)),
            };
          } catch {
            return { slug, peak: "--:--", calm: "--:--", maxPred: 0 };
          }
        }),
      );
      if (mounted) setQuickForecast(rows);
    })();
    return () => {
      mounted = false;
    };
  }, [favoriteSlugs]);

  return (
    <main className="relative min-h-[calc(100vh-80px)] bg-[#050505] font-display text-white">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_20%_20%,rgba(79,70,229,0.12)_0%,transparent_30%),radial-gradient(circle_at_80%_70%,rgba(236,72,153,0.08)_0%,transparent_30%)]" />

      <div className="relative z-10 mx-auto w-full max-w-3xl px-4 pb-16 pt-10">
        <h1 className="text-3xl font-black tracking-tight">マイページ</h1>
        <p className="mt-2 text-sm text-white/60">
          閲覧履歴・お気に入りはこのブラウザにだけ保存されます（アカウント連携なし）。
        </p>

        <section className="mt-8 space-y-3">
          <h2 className="text-sm font-semibold text-amber-100/90">すぐに移動</h2>
          <div className="flex flex-wrap gap-2">
            <Link
              href="/stores"
              className="rounded-full border border-white/15 bg-white/5 px-3 py-1.5 text-xs font-medium text-white/85 hover:border-amber-400/50 hover:text-amber-100"
            >
              店舗一覧
            </Link>
            <Link
              href="/blog"
              className="rounded-full border border-white/15 bg-white/5 px-3 py-1.5 text-xs font-medium text-white/85 hover:border-amber-400/50 hover:text-amber-100"
            >
              ブログ
            </Link>
            <Link
              href="/insights/weekly"
              className="rounded-full border border-white/15 bg-white/5 px-3 py-1.5 text-xs font-medium text-white/85 hover:border-amber-400/50 hover:text-amber-100"
            >
              週次 Insights
            </Link>
            <Link
              href="/"
              className="rounded-full border border-white/15 bg-white/5 px-3 py-1.5 text-xs font-medium text-white/85 hover:border-amber-400/50 hover:text-amber-100"
            >
              ホーム
            </Link>
          </div>
        </section>

        <section className="mt-10 space-y-3">
          <div className="flex items-center justify-between gap-2">
            <h2 className="text-sm font-semibold text-amber-100/90">お気に入り店舗</h2>
            {favoriteSlugs.length > 0 && (
              <button
                type="button"
                onClick={() => {
                  clearFavoriteStores();
                  refresh();
                }}
                className="text-[11px] text-white/45 underline-offset-2 hover:text-amber-200/90 hover:underline"
              >
                すべて解除
              </button>
            )}
          </div>
          {favoriteSlugs.length === 0 ? (
            <p className="rounded-2xl border border-dashed border-white/15 bg-white/[0.03] p-4 text-sm text-white/50">
              店舗ページの「お気に入りに追加」から登録できます。
            </p>
          ) : (
            <ul className="space-y-2">
              {favoriteSlugs.map((slug) => {
                const m = slugToMeta(slug);
                return (
                  <li
                    key={slug}
                    className="flex items-center justify-between gap-3 rounded-2xl border border-white/10 bg-white/[0.04] px-4 py-3"
                  >
                    <Link
                      href={`/store/${m.slug}?store=${m.slug}`}
                      className="min-w-0 flex-1 text-sm font-medium text-white hover:text-amber-200"
                    >
                      Oriental Lounge {m.label}
                      <span className="mt-0.5 block text-[11px] font-normal text-white/45">{m.areaLabel}</span>
                    </Link>
                    <button
                      type="button"
                      onClick={() => {
                        removeFavoriteStore(slug);
                        refresh();
                      }}
                      className="shrink-0 rounded-md border border-white/15 px-2 py-1 text-[11px] text-white/60 hover:border-rose-400/40 hover:text-rose-200"
                    >
                      解除
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        {favoriteSlugs.length > 0 && (
          <section className="mt-10 space-y-3">
            <h2 className="text-sm font-semibold text-emerald-100/90">お気に入り店舗の今日の予測（ML 2.0）</h2>
            <div className="grid gap-2">
              {quickForecast.map((f) => {
                const m = slugToMeta(f.slug);
                return (
                  <Link
                    key={`quick-${f.slug}`}
                    href={`/store/${m.slug}?store=${m.slug}`}
                    className="grid grid-cols-1 gap-2 rounded-2xl border border-emerald-400/20 bg-emerald-500/5 px-4 py-3 text-sm text-white/90 md:grid-cols-4"
                  >
                    <span className="font-semibold">Oriental Lounge {m.label}</span>
                    <span className="text-xs text-white/65">ピーク目安: {f.peak}</span>
                    <span className="text-xs text-white/65">落ち着き目安: {f.calm}</span>
                    <span className="text-xs text-white/65">最大予測: {f.maxPred}人</span>
                  </Link>
                );
              })}
            </div>
          </section>
        )}

        <section className="mt-10 space-y-3">
          <div className="flex items-center justify-between gap-2">
            <h2 className="text-sm font-semibold text-amber-100/90">最近見た店舗</h2>
            {historySlugs.length > 0 && (
              <button
                type="button"
                onClick={() => {
                  clearStoreHistory();
                  refresh();
                }}
                className="text-[11px] text-white/45 underline-offset-2 hover:text-amber-200/90 hover:underline"
              >
                履歴を消す
              </button>
            )}
          </div>
          {historySlugs.length === 0 ? (
            <p className="rounded-2xl border border-dashed border-white/15 bg-white/[0.03] p-4 text-sm text-white/50">
              店舗ダッシュボードを開くと、ここに最大12件まで表示されます。
            </p>
          ) : (
            <ul className="space-y-2">
              {historySlugs.map((slug) => {
                const m = slugToMeta(slug);
                return (
                  <li key={`${slug}-hist`}>
                    <Link
                      href={`/store/${m.slug}?store=${m.slug}`}
                      className="block rounded-2xl border border-white/10 bg-white/[0.04] px-4 py-3 text-sm font-medium text-white transition hover:border-amber-400/35 hover:bg-amber-500/5"
                    >
                      Oriental Lounge {m.label}
                      <span className="mt-0.5 block text-[11px] font-normal text-white/45">{m.areaLabel}</span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        <section className="mt-10 rounded-2xl border border-white/10 bg-white/[0.03] p-5 text-sm text-white/55">
          <p className="font-medium text-white/70">今後の拡張（構想）</p>
          <ul className="mt-2 list-disc space-y-1 pl-5">
            <li>通知（混雑・雨など）— インフラ・権限が重いためフェーズ後半向け</li>
            <li>アカウントでお気に入り同期 — ログイン基盤が必要</li>
          </ul>
        </section>
      </div>
    </main>
  );
}
