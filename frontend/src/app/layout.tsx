import "./globals.css";
import type { Metadata } from "next";
import { Suspense } from "react";
import { MeguribiHeader } from "@/components/MeguribiHeader";
import { GoogleAnalytics } from "@/components/GoogleAnalytics";
import { getMetadataBaseUrl } from "@/lib/siteUrl";
import { serializeJsonLd } from "@/lib/jsonLd";

const base = getMetadataBaseUrl();

// Service Worker のキャッシュを毎デプロイで確実に入れ替えるためのバージョン識別子。
// public/sw.js はビルドパイプラインを通らない静的ファイルなのでファイル自体は変わらないが、
// 登録URLにクエリを付ければブラウザは新しい SW として再インストールし、
// activate ハンドラの古キャッシュ削除（sw.js 側で CACHE_NAME にこの値を含める）が効くようになる。
// Vercel が自動設定する VERCEL_GIT_COMMIT_SHA を優先し、無ければビルド時刻でフォールバックする
// （どちらもサーバー専用envで足りる。sw.js 登録スクリプトはビルド時にこの値で埋め込まれる）。
const SW_VERSION =
  process.env.VERCEL_GIT_COMMIT_SHA?.trim().slice(0, 12) ||
  process.env.NEXT_PUBLIC_BUILD_ID?.trim() ||
  String(Date.now());

const siteJsonLd = serializeJsonLd([
  {
    "@context": "https://schema.org",
    "@type": "WebSite",
    name: "めぐりび",
    alternateName: "MEGRIBI",
    url: base.href,
  },
  {
    "@context": "https://schema.org",
    "@type": "Organization",
    name: "めぐりび",
    url: base.href,
    logo: new URL("/icons/icon-192.png", base).href,
  },
]);

export const metadata: Metadata = {
  metadataBase: base,
  title: {
    default: "めぐりび | MEGRIBI",
    template: "%s | めぐりび",
  },
  description:
    "オリエンタルラウンジの混雑傾向・男女比・予測をまとめてチェック。今夜の一軒をデータで選ぶための案内灯。",
  applicationName: "めぐりび",
  manifest: "/manifest.json",
  icons: {
    icon: "/icons/icon.svg",
    apple: "/icons/icon-192.png",
  },
  openGraph: {
    type: "website",
    locale: "ja_JP",
    siteName: "めぐりび",
    title: "めぐりび | MEGRIBI",
    description:
      "オリエンタルラウンジの混雑傾向・男女比・予測をまとめてチェック。今夜の一軒をデータで選ぶための案内灯。",
    url: base,
  },
  twitter: {
    card: "summary_large_image",
    title: "めぐりび | MEGRIBI",
    description:
      "オリエンタルラウンジの混雑傾向・男女比・予測をまとめてチェック。今夜の一軒をデータで選ぶための案内灯。",
  },
  robots: {
    index: true,
    follow: true,
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ja">
      <head>
        <meta name="theme-color" content="#000000" />
        <meta name="mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
        <meta name="apple-mobile-web-app-title" content="めぐりび" />
        {/* GA (gtag.js) は afterInteractive で別ホストから読み込まれるため、早期に名前解決/接続しておく。
            同一オリジンの /api はプリコネクト不要。 */}
        <link rel="preconnect" href="https://www.googletagmanager.com" crossOrigin="" />
        <link rel="dns-prefetch" href="https://www.googletagmanager.com" />
        <link rel="preconnect" href="https://www.google-analytics.com" crossOrigin="" />
        <link rel="dns-prefetch" href="https://www.google-analytics.com" />
      </head>
      <body className="bg-black">
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: siteJsonLd }}
        />
        <Suspense>
          <GoogleAnalytics />
        </Suspense>
        <script
          dangerouslySetInnerHTML={{
            __html: `if("serviceWorker"in navigator){window.addEventListener("load",function(){navigator.serviceWorker.register("/sw.js?v=${SW_VERSION}")})}`,
          }}
        />
        <MeguribiHeader />
        <div className="min-h-screen text-slate-50">{children}</div>
        <footer className="border-t border-white/5 bg-black px-4 py-6 text-center text-[11px] text-white/30">
          <nav className="mx-auto flex max-w-6xl flex-wrap items-center justify-center gap-x-4 gap-y-1">
            <a href="/terms" className="hover:text-white/60">利用規約</a>
            <a href="/privacy" className="hover:text-white/60">プライバシーポリシー</a>
            <a href="/disclaimer" className="hover:text-white/60">免責事項</a>
            <a href="/contact" className="hover:text-white/60">お問い合わせ</a>
          </nav>
          <p className="mt-2">
            &copy; {new Date().getFullYear()} めぐりび (MEGRIBI) — 本サービスは各相席ブランドの公式サービスではありません
          </p>
        </footer>
      </body>
    </html>
  );
}
