import type { Metadata } from "next";
import { buildPageMetadata } from "@/lib/seo/pageMetadata";
import MyPageClient from "./mypage-client";

export const metadata: Metadata = buildPageMetadata({
  title: "マイページ",
  description: "お気に入り店舗・最近見た店舗（このブラウザに保存）。店舗一覧・ブログ・週次 Insights へのショートカット。",
  path: "/mypage",
  ogDescription: "お気に入り・閲覧履歴（端末内）と主要ページへのリンク。",
  canonical: false,
  // 2026-08-22 総合レビュー対応（検証記録は memory/general-review-2026-08-22.md）:
  // robots.ts の Disallow はクロール抑止であってインデックス抑止ではない（外部から張られたリンク
  // 経由でインデックスされ得る）。個人の端末内お気に入りを表示するだけのページなので明示的に noindex。
  robots: { index: false, follow: false },
});

export default function MyPage() {
  return <MyPageClient />;
}
