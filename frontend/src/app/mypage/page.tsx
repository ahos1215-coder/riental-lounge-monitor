import type { Metadata } from "next";
import { buildPageMetadata } from "@/lib/seo/pageMetadata";
import MyPageClient from "./mypage-client";

export const metadata: Metadata = buildPageMetadata({
  title: "マイページ",
  description: "お気に入り店舗・最近見た店舗（このブラウザに保存）。店舗一覧・ブログ・週次 Insights へのショートカット。",
  path: "/mypage",
  ogDescription: "お気に入り・閲覧履歴（端末内）と主要ページへのリンク。",
  canonical: false,
});

export default function MyPage() {
  return <MyPageClient />;
}
