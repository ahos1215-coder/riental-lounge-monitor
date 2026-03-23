import type { Metadata } from "next";
import { getMetadataBaseUrl } from "@/lib/siteUrl";
import MyPageClient from "./mypage-client";

const base = getMetadataBaseUrl();

export const metadata: Metadata = {
  title: "マイページ",
  description: "お気に入り店舗・最近見た店舗（このブラウザに保存）。店舗一覧・ブログ・週次 Insights へのショートカット。",
  openGraph: {
    title: "マイページ | めぐりび",
    description: "お気に入り・閲覧履歴（端末内）と主要ページへのリンク。",
    url: new URL("/mypage", base),
    type: "website",
    locale: "ja_JP",
  },
  twitter: {
    card: "summary_large_image",
    title: "マイページ | めぐりび",
    description: "お気に入り・閲覧履歴（端末内）と主要ページへのリンク。",
  },
};

export default function MyPage() {
  return <MyPageClient />;
}
