"use client";

import Link from "next/link";
import { MapPin } from "lucide-react";
import { FadeIn } from "@/components/ui/FadeIn";
import { STORES } from "@/app/config/stores";
import type { HomeRepresentativeStore } from "./homeTypes";

export function HomeStoreDirectory({
  representativeStores,
}: {
  representativeStores: HomeRepresentativeStore[];
}) {
  return (
          <FadeIn delay={0.15} id="store-directory" className="scroll-mt-24 space-y-3">
            <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-100">
              <MapPin size={14} className="text-amber-400" />
              店舗の男女比・予測を見る
            </h2>
            <div className="rounded-2xl border border-slate-800 bg-slate-950/80 p-4 text-sm leading-relaxed text-slate-100/85">
              <p>
                相席ラウンジ（オリエンタルラウンジ・相席屋）{" "}
                <span className="font-semibold text-slate-100">{STORES.length}</span>
                店舗の実測・予測は、
                <strong className="font-medium text-indigo-200">店舗一覧</strong>
                にまとめています。地域での絞り込み・検索・ページ送りで探せます。
              </p>
              <p className="mt-2 text-[13px] text-slate-400">
                トップでは「直前に見た店」の推移だけを表示し、特定店の抜粋一覧は出しません（一覧と役割が重なるため）。
              </p>
              {representativeStores.length > 0 && (
                <ul className="mt-4 flex flex-wrap gap-2">
                  {representativeStores.map((store) => (
                    <li key={store.slug}>
                      <Link
                        href={`/store/${store.slug}`}
                        className="inline-flex items-center rounded-full border border-slate-700 bg-slate-900/60 px-3 py-1 text-[11px] text-slate-300 transition hover:border-indigo-400/60 hover:text-indigo-200"
                      >
                        {store.name}（{store.areaLabel}）
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
              <div className="mt-4">
                <Link
                  href="/stores"
                  className="inline-flex items-center justify-center rounded-md bg-indigo-500 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-400"
                >
                  店舗一覧を開く
                </Link>
              </div>
            </div>
          </FadeIn>
  );
}
