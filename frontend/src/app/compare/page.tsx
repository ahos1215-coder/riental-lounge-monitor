import type { Metadata } from "next";
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

export default function ComparePage() {
  return <CompareClient />;
}
