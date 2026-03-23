import type { Metadata } from "next";
import { formatYmdToSlash, getAllPostMetas } from "@/lib/blog/content";
import { getMetadataBaseUrl } from "@/lib/siteUrl";
import HomePage from "./home-client";

const base = getMetadataBaseUrl();

export const metadata: Metadata = {
  title: "ホーム",
  description:
    "今夜のオリエンタルラウンジをデータで選ぶ。店舗一覧・ブログ・混雑の読み方をめぐりびから。",
  openGraph: {
    title: "めぐりび | ホーム",
    description:
      "今夜のオリエンタルラウンジをデータで選ぶ。店舗一覧・ブログ・混雑の読み方をめぐりびから。",
    url: new URL("/", base),
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "めぐりび | ホーム",
    description:
      "今夜のオリエンタルラウンジをデータで選ぶ。店舗一覧・ブログ・混雑の読み方をめぐりびから。",
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
