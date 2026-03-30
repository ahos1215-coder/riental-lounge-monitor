import type { Metadata } from "next";
import dynamic from "next/dynamic";
import { getMetadataBaseUrl } from "@/lib/siteUrl";

const CompareClient = dynamic(() => import("./compare-client"), {
  ssr: false,
  loading: () => (
    <div className="mx-auto max-w-6xl px-4 py-8">
      <div className="h-8 w-48 animate-pulse rounded bg-slate-800/60" />
      <div className="mt-6 grid gap-4 md:grid-cols-3">
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-64 animate-pulse rounded-2xl bg-slate-800/60" />
        ))}
      </div>
    </div>
  ),
});

const base = getMetadataBaseUrl();

export const metadata: Metadata = {
  title: "店舗比較",
  description: "オリエンタルラウンジの店舗を並べて比較。リアルタイムの混雑状況・男女比をチェック。",
  openGraph: {
    title: "店舗比較 | めぐりび",
    description: "店舗を並べて混雑状況・男女比を比較します。",
    url: new URL("/compare", base),
    type: "website",
    locale: "ja_JP",
  },
};

export default function ComparePage() {
  return <CompareClient />;
}
