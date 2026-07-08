import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { getMetadataBaseUrl } from "@/lib/siteUrl";
import { STORES, buildStoreFullName } from "@/app/config/stores";
import { ReportsPageClient } from "./reports-client";
import ReportsLoading from "./loading";

const base = getMetadataBaseUrl();

export const metadata: Metadata = {
  title: "AI予測レポート（Daily / Weekly）",
  description:
    "オリエンタルラウンジ全店舗のAI予測レポートを一覧で確認。毎日自動更新のDaily Reportと毎週水曜のWeekly Reportを、エリア・店舗名で素早く探せます。",
  alternates: { canonical: new URL("/reports", base).href },
  openGraph: {
    title: "AI予測レポート | めぐりび",
    description:
      "全店舗のAI予測レポートをDaily/Weeklyで一覧確認。",
    url: new URL("/reports", base),
    type: "website",
  },
};

/**
 * ReportsPageClient はレポート一覧をクライアント側 fetch (/api/reports/list) で描画するため、
 * raw HTML には /reports/{daily,weekly}/{slug} への実アンカーが載らない。ここで全店舗分を
 * サーバー側で列挙し、実際にレポートが生成済みかどうかに関わらず両レポート種別へのリンクを
 * raw HTML に出す（未生成分は各レポートページ側が空状態を表示する既存挙動に委ねる）。
 */
function AllStoresReportsSsrNav() {
  return (
    <section aria-labelledby="all-reports-heading" className="mx-auto max-w-5xl px-4 pb-10">
      <h2 id="all-reports-heading" className="text-sm font-semibold text-white/60">
        各店のレポート
      </h2>
      <p className="mt-1 text-[11px] text-white/40">
        全{STORES.length}店舗のDaily / Weeklyレポートへ直接移動できます。
      </p>
      <nav aria-label="各店のレポート一覧" className="mt-3">
        <ul className="flex flex-wrap gap-x-4 gap-y-2">
          {STORES.map((store) => (
            <li key={store.slug} className="text-xs text-white/50">
              <span className="text-white/70">{buildStoreFullName(store)}</span>
              <span className="ml-2 inline-flex gap-2">
                <Link
                  href={`/reports/daily/${store.slug}`}
                  className="underline decoration-white/20 underline-offset-2 transition hover:text-indigo-200 hover:decoration-indigo-300"
                >
                  Daily
                </Link>
                <Link
                  href={`/reports/weekly/${store.slug}`}
                  className="underline decoration-white/20 underline-offset-2 transition hover:text-amber-200 hover:decoration-amber-300"
                >
                  Weekly
                </Link>
              </span>
            </li>
          ))}
        </ul>
      </nav>
    </section>
  );
}

export default function ReportsPage() {
  return (
    <>
      <Suspense fallback={<ReportsLoading />}>
        <ReportsPageClient />
      </Suspense>
      <AllStoresReportsSsrNav />
    </>
  );
}
