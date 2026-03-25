"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import type { StoreMeta } from "@/app/config/stores";
import { GenderRatioBar } from "./GenderRatioBar";

export type HeroRealtime = {
  men: number;
  women: number;
  nowTotal: number;
  peakLabel: string;
  calmLabel: string;
  maxPred: number;
  crowdLevel: string;
};

type HomeHeroSectionProps = {
  meta: StoreMeta;
  /** お気に入り優先 / 前回閲覧 / 既定 / この店舗のいま など */
  contextLabel: string;
  data: HeroRealtime | null;
  loading: boolean;
  /** トップ用は home（デフォルト）。店舗詳細では store を指定 */
  variant?: "home" | "store";
  /** 店舗ページでお気に入りボタンなどを右上に置く */
  headerRight?: ReactNode;
};

function microcopyFromCrowd(crowd: string): { emoji: string; text: string } | null {
  if (crowd === "空いている") return { emoji: "✨", text: "今が狙い目の目安です（入店しやすさ重視）" };
  if (crowd === "ほどよい") return { emoji: "◎", text: "ほどよい賑わいの目安です" };
  if (crowd === "混雑") return { emoji: "🔥", text: "賑わいが強めの時間帯の目安です" };
  return null;
}

export function HomeHeroSection({
  meta,
  contextLabel,
  data,
  loading,
  variant = "home",
  headerRight,
}: HomeHeroSectionProps) {
  const href = `/store/${meta.slug}?store=${meta.slug}`;
  const isStore = variant === "store";
  const eyebrow = isStore ? "リアルタイム" : "注目";

  return (
    <section className="relative overflow-hidden rounded-3xl border border-white/[0.08] bg-gradient-to-b from-slate-950 via-slate-950/95 to-black p-5 shadow-[0_0_0_1px_rgba(255,255,255,0.04),0_24px_64px_rgba(0,0,0,0.55)] md:p-7">
      <div
        className="pointer-events-none absolute -right-16 -top-24 h-56 w-56 rounded-full bg-fuchsia-600/15 blur-3xl"
        aria-hidden
      />
      <div
        className="pointer-events-none absolute -left-12 top-0 h-44 w-44 rounded-full bg-cyan-500/12 blur-3xl"
        aria-hidden
      />

      <div className="relative z-10">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-[10px] font-semibold tracking-[0.18em] text-slate-500">{eyebrow}</p>
            <p className="mt-1 text-[11px] text-amber-200/80">{contextLabel}</p>
            <h2 className="mt-2 text-lg font-bold leading-snug tracking-tight text-white md:text-xl">
              Oriental Lounge {meta.label}
            </h2>
            <p className="mt-0.5 text-xs text-slate-500">{meta.areaLabel}</p>
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            {headerRight}
            {!isStore && (
              <Link
                href={href}
                className="rounded-full border border-white/15 bg-white/5 px-3 py-1.5 text-[11px] font-semibold text-white/90 transition hover:border-amber-400/40 hover:bg-amber-500/10 hover:text-amber-100"
              >
                詳しく見る
              </Link>
            )}
          </div>
        </div>

        {loading ? (
          <div className="mt-8 space-y-4">
            <div className="flex gap-4">
              <div className="h-20 flex-1 animate-pulse rounded-2xl bg-slate-800/80" />
              <div className="h-20 flex-1 animate-pulse rounded-2xl bg-slate-800/80" />
            </div>
            <div className="h-3 w-full animate-pulse rounded-full bg-slate-800/80" />
          </div>
        ) : !data ? (
          <p className="mt-8 rounded-2xl border border-white/10 bg-white/[0.03] px-4 py-6 text-center text-sm text-slate-400">
            リアルタイムデータを取得できませんでした。
            <Link href={href} className="mt-2 block font-medium text-indigo-300 hover:text-indigo-200">
              店舗ページで開く
            </Link>
          </p>
        ) : (
          <>
            <div className="mt-8 grid grid-cols-2 gap-3 md:gap-4">
              <div className="rounded-2xl border border-cyan-500/25 bg-cyan-950/30 px-4 py-4 text-center ring-1 ring-cyan-400/20 md:py-5">
                <p className="text-[10px] font-semibold uppercase tracking-wider text-cyan-200/70">男性</p>
                <p
                  className="mt-1 tabular-nums text-4xl font-black tracking-tight text-transparent md:text-5xl"
                  style={{
                    background: "linear-gradient(180deg, #a5f3fc 0%, #22d3ee 45%, #0891b2 100%)",
                    WebkitBackgroundClip: "text",
                    backgroundClip: "text",
                    filter: "drop-shadow(0 0 20px rgba(34, 211, 238, 0.35))",
                  }}
                >
                  {data.men}
                </p>
                <p className="mt-0.5 text-[10px] text-cyan-200/50">名</p>
              </div>
              <div className="rounded-2xl border border-pink-500/25 bg-pink-950/25 px-4 py-4 text-center ring-1 ring-pink-400/20 md:py-5">
                <p className="text-[10px] font-semibold uppercase tracking-wider text-pink-200/70">女性</p>
                <p
                  className="mt-1 tabular-nums text-4xl font-black tracking-tight text-transparent md:text-5xl"
                  style={{
                    background: "linear-gradient(180deg, #fbcfe8 0%, #ec4899 45%, #be185d 100%)",
                    WebkitBackgroundClip: "text",
                    backgroundClip: "text",
                    filter: "drop-shadow(0 0 18px rgba(236, 72, 153, 0.35))",
                  }}
                >
                  {data.women}
                </p>
                <p className="mt-0.5 text-[10px] text-pink-200/50">名</p>
              </div>
            </div>

            <p className="mt-4 text-center text-xs text-slate-400">
              店内の目安 <span className="font-semibold text-slate-200">{data.nowTotal}</span> 名
            </p>

            <div className="mt-5">
              <GenderRatioBar men={data.men} women={data.women} />
            </div>

            <div className="mt-6 flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center sm:gap-2">
              <span className="inline-flex items-center gap-1.5 rounded-full border border-amber-500/30 bg-amber-500/10 px-3 py-1.5 text-[11px] font-medium text-amber-100/95">
                <span aria-hidden>🔥</span>
                <span>
                  {data.peakLabel !== "--:--"
                    ? `${data.peakLabel} 頃にピークの予測（最大 ${data.maxPred} 名目安）`
                    : "ピーク予測を取得中です"}
                </span>
              </span>
              {data.calmLabel !== "--:--" && (
                <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-500/25 bg-emerald-500/10 px-3 py-1.5 text-[11px] font-medium text-emerald-100/90">
                  <span aria-hidden>🌙</span>
                  <span>{data.calmLabel} 頃は落ち着きやすい目安</span>
                </span>
              )}
              {(() => {
                const tip = microcopyFromCrowd(data.crowdLevel);
                if (!tip) return null;
                return (
                  <span className="inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.04] px-3 py-1.5 text-[11px] text-slate-200/90">
                    <span aria-hidden>{tip.emoji}</span>
                    <span>{tip.text}</span>
                  </span>
                );
              })()}
            </div>
          </>
        )}
      </div>
    </section>
  );
}
