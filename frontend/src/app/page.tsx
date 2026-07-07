import type { Metadata } from "next";
import { formatYmdToSlash, getAllPostMetas } from "@/lib/blog/content";
import { getMetadataBaseUrl } from "@/lib/siteUrl";
import { fetchBackendSnapshot } from "@/lib/serverSnapshot";
import HomePage, { type HomeMegribiScoreItem } from "./home-client";

const base = getMetadataBaseUrl();

/** TOP5は数分単位の粒度で十分（/api/megribi_score 自体のCDN TTLは120s）。 */
export const revalidate = 180;

type MegribiScoreResponse = {
  ok?: boolean;
  data?: HomeMegribiScoreItem[];
};

export const metadata: Metadata = {
  title: "めぐりび | 相席ラウンジの混雑予測・リアルタイム人数",
  description:
    "相席ラウンジの混雑状況をリアルタイムで確認。AIが今夜のピーク時間を予測し、ベストな来店タイミングの参考をお届けします。全国44店舗対応。",
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
      "相席ラウンジの混雑状況をリアルタイムで確認。AIが今夜のピーク時間を予測。全国44店舗対応。",
  },
};

/**
 * トップの「今夜のおすすめ TOP5」用スコアをサーバー側で先取り取得する。
 * 失敗・タイムアウト時は null を返し、HomePage 側は従来通りクライアント fetch のみで描画する
 * （コールドスタート/バックエンド不調時も build・初期表示を落とさない）。
 */
async function fetchInitialTop5(): Promise<HomeMegribiScoreItem[] | null> {
  const json = await fetchBackendSnapshot<MegribiScoreResponse>("/api/megribi_score", 180);
  if (!json?.ok || !Array.isArray(json.data)) return null;
  return json.data;
}

export default async function Page() {
  const posts = getAllPostMetas().slice(0, 3);
  const latestBlogPosts = posts.map((p) => ({
    slug: p.slug,
    title: p.title,
    categoryLabel: p.categoryLabel,
    dateLabel: formatYmdToSlash(p.date),
  }));

  const initialTop5 = await fetchInitialTop5();

  return <HomePage latestBlogPosts={latestBlogPosts} initialTop5={initialTop5} />;
}
