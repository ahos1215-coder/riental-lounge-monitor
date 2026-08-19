import type { Metadata } from "next";

import { getMetadataBaseUrl } from "@/lib/siteUrl";

/**
 * ページ共通の SEO メタ（title / description / canonical / OG / Twitter）を1箇所で組み立てる。
 *
 * root layout の `title.template` は `<title>` にしか効かないため、OG/Twitter の見出しには
 * 各ページが自分でサイト名を付ける必要がある。その付け方（および「付けない」という例外）を
 * 引数として明示させるのがこのヘルパーの目的。
 *
 * 現状のページごとの例外は暗黙の既定値ではなく必ず引数で表現する（揃えると表示が変わるため、
 * 揃えるかどうかはオーナー判断）:
 *   - /blog/[slug]      … OG/Twitter title に接尾辞を付けない（socialTitle に title をそのまま渡す）
 *   - /reports/daily/*  … noindex のため canonical 無し（canonical: false + robots 指定）
 *   - /mypage, /compare … canonical 無し
 *   - /reports, /compare… Twitter カード無し（twitter: false）
 *   - /, /reports       … og:locale 無し（ogLocale: null）
 */

/** OG/Twitter の見出しに付けるサイト名の接尾辞。 */
export const SOCIAL_TITLE_SUFFIX = " | めぐりび";

export type PageMetadataInput = {
  /** `<title>`（root layout の template で " | めぐりび" が付く） */
  title: string;
  description: string;
  /** サイト原点からの絶対パス（例 "/store/shibuya"）。canonical と og:url に使う。 */
  path: string;
  /** 既定 "website"。レポート・記事系は "article"。 */
  ogType?: "website" | "article";
  /** 既定 "ja_JP"。null を渡すと og:locale を出力しない（現状維持用）。 */
  ogLocale?: string | null;
  /** 既定 true。false で canonical を出さない。 */
  canonical?: boolean;
  robots?: Metadata["robots"];
  /** OG/Twitter の見出し。既定は `title + " | めぐりび"`。 */
  socialTitle?: string;
  /** OG の説明。既定は description。 */
  ogDescription?: string;
  /** 既定 true。false で Twitter カードを出さない（現状維持用）。 */
  twitter?: boolean;
  /** Twitter の見出しを OG と変える場合のみ指定。 */
  twitterTitle?: string;
  /** Twitter の説明を OG と変える場合のみ指定。 */
  twitterDescription?: string;
};

export function buildPageMetadata(input: PageMetadataInput): Metadata {
  const {
    title,
    description,
    path,
    ogType = "website",
    ogLocale = "ja_JP",
    canonical = true,
    robots,
    socialTitle = `${title}${SOCIAL_TITLE_SUFFIX}`,
    ogDescription = description,
    twitter = true,
    twitterTitle = socialTitle,
    twitterDescription = ogDescription,
  } = input;

  const url = new URL(path, getMetadataBaseUrl());

  return {
    title,
    description,
    alternates: canonical ? { canonical: url.href } : undefined,
    robots,
    openGraph: {
      title: socialTitle,
      description: ogDescription,
      url,
      type: ogType,
      locale: ogLocale ?? undefined,
    },
    twitter: twitter
      ? {
          card: "summary_large_image",
          title: twitterTitle,
          description: twitterDescription,
        }
      : undefined,
  };
}
