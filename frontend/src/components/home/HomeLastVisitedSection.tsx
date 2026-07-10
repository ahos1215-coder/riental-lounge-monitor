"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { Clock } from "lucide-react";
import { FadeIn } from "@/components/ui/FadeIn";
import { buildStoreFullName, type StoreMeta } from "@/app/config/stores";
import { FALLBACK_LAST_STORE, getAreaLabelFromSlug } from "./homeHelpers";

export function HomeLastVisitedSection({
  lastStore,
  chart,
}: {
  lastStore: StoreMeta | null;
  chart: ReactNode;
}) {
  return (
          <FadeIn delay={0.3} id="last-visited" className="scroll-mt-24 space-y-3">
            <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-100">
              <Clock size={14} className="text-slate-400" />
              Last visited store
            </h2>
            <div className="rounded-2xl border border-slate-800 bg-slate-950/80 px-4 py-4">
              <div className="grid gap-4 md:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)] md:items-center">
                <div>
                  {lastStore ? (
                    <>
                      <p className="text-[11px] text-slate-400">Last visited</p>
                      <p className="mt-1 text-lg font-semibold text-slate-50">
                        {buildStoreFullName(lastStore)}
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
                  {chart}
                </div>
              </div>
            </div>
          </FadeIn>
  );
}
