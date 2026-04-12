import type { Metadata } from "next";
import { formatYmdToSlash, getAllPostMetas } from "@/lib/blog/content";
import { getMetadataBaseUrl } from "@/lib/siteUrl";
import HomePage from "./home-client";

const base = getMetadataBaseUrl();

export const metadata: Metadata = {
  title: "めぐりび | 相席ラウンジの混雑予測・リアルタイム人数",
  description:
    "相席ラウンジの混雑状況をリアルタイムで確認。AIが今夜のピーク時間を予測し、ベストな来店タイミングの参考をお届けします。全国38店舗対応。",
  openGraph: {
    title: "めぐりび | 相席ラウンジの混雑予測・リアルタイム人数",
    description:
      "相席ラウンジの混雑状況をリアルタイムで確認。AIが今夜のピーク時間を予測し、ベストな来店タイミングの参考をお届けします。",
    url: new URL("/", base),
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "めぐりび | 相席ラウンジの混雑予測",
    description:
      "相席ラウンジの混雑状況をリアルタイムで確認。AIが今夜のピーク時間を予測。全国38店舗対応。",
  },
};

export default function Page() {
  const posts = getAllPostMetas().slice(0, 3);
  const latestBlogPosts = posts.map((p) => ({
    slug: p.slug,
    title: p.title,
    categoryLabel: p.categoryLabel,
    dateLabel: formatYmdToSlash(p.date),
  }));

  return <HomePage latestBlogPosts={latestBlogPosts} />;
}
