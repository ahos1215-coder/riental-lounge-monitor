"use client";

import Link from "next/link";
import { TrendingUp, ChevronRight } from "lucide-react";
import { FadeIn } from "@/components/ui/FadeIn";
import { getStoreMetaBySlug, isPercentCrowdBrand } from "@/app/config/stores";
import type { MegribiScoreItem } from "./homeTypes";

function ScoreBar({ score }: { score: number }) {
  const pct = Math.round(score * 100);
  const color =
    pct >= 70
      ? "bg-emerald-400"
      : pct >= 40
        ? "bg-amber-400"
        : "bg-slate-500";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-slate-800">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-[10px] font-bold tabular-nums text-white/70">{pct}</span>
    </div>
  );
}

export function HomeTonightTop5({
  topStores,
  topStoresLoading,
}: {
  topStores: MegribiScoreItem[];
  topStoresLoading: boolean;
}) {
  return (
          <FadeIn delay={0.2} className="scroll-mt-24 space-y-3">
            <div className="flex items-end justify-between gap-3">
              <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-100">
                <TrendingUp size={14} className="text-emerald-400" />
                今夜のおすすめ
              </h2>
              <Link href="/stores" className="flex items-center gap-1 text-xs text-indigo-300 transition hover:text-indigo-200">
                全店舗スコアを見る <ChevronRight size={12} />
              </Link>
            </div>
            <p className="text-[11px] text-slate-500">
              めぐりびスコア（混雑率 × 女性比率）が高い順にピックアップ。
            </p>
            {topStoresLoading ? (
              <div className="grid gap-2 sm:grid-cols-5">
                {[...Array(5)].map((_, i) => (
                  <div
                    key={i}
                    className="h-24 animate-pulse rounded-xl border border-slate-800 bg-slate-900/40"
                  />
                ))}
              </div>
            ) : topStores.length === 0 ? (
              <div className="rounded-2xl border border-slate-800 bg-slate-950/80 p-4 text-sm text-slate-400">
                現在スコアを計算中です。しばらくしてからお試しください。
              </div>
            ) : (
              <div className="grid gap-2 sm:grid-cols-5">
                {topStores.map((item, idx) => {
                  const meta = getStoreMetaBySlug(item.slug);
                  return (
                    <Link
                      key={item.slug}
                      href={`/store/${item.slug}?store=${item.slug}`}
                      className="group flex flex-col items-center rounded-xl border border-slate-800 bg-slate-950/80 px-3 py-3 text-center transition hover:border-emerald-500/50 hover:bg-slate-900/80"
                    >
                      <span className="text-[10px] font-bold text-emerald-300/70">
                        #{idx + 1}
                      </span>
                      <span className="mt-1 text-xs font-bold text-white group-hover:text-emerald-200">
                        {meta.label}
                      </span>
                      <span className="mt-0.5 text-[10px] text-white/35">{meta.areaLabel}</span>
                      <div className="mt-1.5">
                        <ScoreBar score={item.score} />
                      </div>
                      <span className="mt-1 text-[9px] text-white/30">
                        {isPercentCrowdBrand(meta.brand) && meta.capacity
                          ? `席 男${item.men_seat_pct ?? 0}% / 女${item.women_seat_pct ?? 0}%`
                          : `${item.total}人（男${item.men} / 女${item.women}）`}
                      </span>
                    </Link>
                  );
                })}
              </div>
            )}
          </FadeIn>
  );
}
