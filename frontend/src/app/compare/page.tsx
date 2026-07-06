import type { Metadata } from "next";
import { Suspense } from "react";
import { getMetadataBaseUrl } from "@/lib/siteUrl";
import CompareClient from "./compare-client";

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

function CompareFallback() {
  return (
    <main className="flex min-h-[calc(100vh-80px)] flex-col items-center justify-center bg-black">
      <div className="flex items-center gap-2 text-white/40">
        <span
          className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-white/20 border-t-indigo-400"
          aria-hidden
        />
        <span className="text-sm">読み込み中…</span>
      </div>
    </main>
  );
}

export default function ComparePage() {
  return (
    <Suspense fallback={<CompareFallback />}>
      <CompareClient />
    </Suspense>
  );
}
