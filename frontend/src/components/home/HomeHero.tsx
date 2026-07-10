"use client";

import Link from "next/link";
import { Sparkles } from "lucide-react";
import { FadeIn } from "@/components/ui/FadeIn";
import { STORES } from "@/app/config/stores";

export function HomeHero() {
  return (
          <FadeIn direction="none" duration={0.6}>
            <div className="relative overflow-hidden rounded-2xl border border-slate-800 bg-gradient-to-br from-slate-950 via-slate-900 to-black">
              <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_15%_20%,rgba(129,140,248,0.45)_0%,transparent_42%),radial-gradient(circle_at_80%_80%,rgba(248,113,113,0.4)_0%,transparent_42%)] opacity-80" />
              <div className="relative z-10 flex flex-col justify-center px-8 py-8 md:px-10 md:py-10">
                <FadeIn delay={0.1} direction="left">
                  <p className="text-[11px] font-semibold tracking-[0.25em] text-indigo-200">
                    MEGRIBI — 相席ラウンジの混雑予測
                  </p>
                </FadeIn>
                <FadeIn delay={0.2}>
                  <h1 className="mt-3 text-3xl font-bold leading-tight tracking-[-0.04em] md:text-4xl">
                    いつ行けば空いてる？
                    <br />
                    <span className="text-indigo-300">AI が教えます。</span>
                  </h1>
                </FadeIn>
                <FadeIn delay={0.35}>
                  <p className="mt-4 max-w-xl text-sm text-slate-100/80">
                    全国 {STORES.length} 店舗の相席ラウンジの混雑状況をリアルタイムで収集。
                    AI が今夜のピーク時間を予測して、ベストな来店タイミングの参考をお届けします。
                  </p>
                </FadeIn>

                {/* 3つの特徴 — 初見ユーザー向け */}
                <FadeIn delay={0.4}>
                  <div className="mt-6 grid grid-cols-1 gap-3 sm:grid-cols-3">
                    <div className="rounded-xl border border-indigo-500/20 bg-indigo-500/5 px-4 py-3">
                      <p className="text-xs font-bold text-indigo-200">リアルタイム混雑</p>
                      <p className="mt-1 text-[11px] text-slate-400">男女別の人数を 5 分ごとに更新</p>
                    </div>
                    <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 px-4 py-3">
                      <p className="text-xs font-bold text-amber-200">AI ピーク予測</p>
                      <p className="mt-1 text-[11px] text-slate-400">今夜何時が一番混むかを予測</p>
                    </div>
                    <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/5 px-4 py-3">
                      <p className="text-xs font-bold text-emerald-200">毎日自動レポート</p>
                      <p className="mt-1 text-[11px] text-slate-400">{STORES.length} 店舗の傾向を毎日 AI が分析</p>
                    </div>
                  </div>
                </FadeIn>

                <FadeIn delay={0.5}>
                <div className="mt-5 flex flex-wrap gap-3 text-sm">
                  <Link
                    href="/stores"
                    className="inline-flex items-center justify-center gap-2 rounded-lg bg-indigo-500 px-5 py-2.5 font-semibold text-white shadow-lg shadow-indigo-500/25 transition-all hover:bg-indigo-400 hover:shadow-indigo-400/30"
                  >
                    <Sparkles size={16} />
                    今すぐ混雑をチェック
                  </Link>
                  <Link
                    href="/reports"
                    className="inline-flex items-center justify-center rounded-md border border-slate-500/60 bg-black/40 px-4 py-2 text-slate-100/80 hover:border-amber-300/80 hover:bg-slate-900"
                  >
                    AI 予測レポートを見る
                  </Link>
                </div>
                <p className="mt-3 max-w-2xl text-[11px] leading-relaxed text-slate-400">
                  表示は参考情報です。予測はモデルによる推定であり、実際の混雑や席状況とは異なることがあります。
                </p>
                </FadeIn>
              </div>
            </div>
          </FadeIn>
  );
}
