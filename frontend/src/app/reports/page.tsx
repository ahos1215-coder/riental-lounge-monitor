import type { Metadata } from "next";

import { getMetadataBaseUrl } from "@/lib/siteUrl";
import { ReportsPageClient } from "./reports-client";

const base = getMetadataBaseUrl();

export const metadata: Metadata = {
  title: "AI予測レポート（Daily / Weekly）",
  description:
    "オリエンタルラウンジ全店舗のAI予測レポートを一覧で確認。毎日自動更新のDaily Reportと毎週水曜のWeekly Reportを、エリア・店舗名で素早く探せます。",
  openGraph: {
    title: "AI予測レポート | めぐりび",
    description:
      "全店舗のAI予測レポートをDaily/Weeklyで一覧確認。",
    url: new URL("/reports", base),
    type: "website",
  },
};

export default function ReportsPage() {
  return <ReportsPageClient />;
}
