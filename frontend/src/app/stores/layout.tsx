import type { Metadata } from "next";
import { getMetadataBaseUrl } from "@/lib/siteUrl";

const base = getMetadataBaseUrl();

export const metadata: Metadata = {
  title: "店舗一覧",
  description: "めぐりびで掲載しているオリエンタルラウンジ全店舗。エリア・店舗名からダッシュボードへ移動できます。",
  openGraph: {
    title: "店舗一覧 | めぐりび",
    description: "オリエンタルラウンジ全店舗の一覧。混雑・男女比は各店舗ページで確認できます。",
    url: new URL("/stores", base),
  },
  twitter: {
    card: "summary_large_image",
    title: "店舗一覧 | めぐりび",
    description: "オリエンタルラウンジ全店舗の一覧。",
  },
};

export default function StoresLayout({ children }: { children: React.ReactNode }) {
  return children;
}
