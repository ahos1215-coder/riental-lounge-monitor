import "./globals.css";
import type { Metadata } from "next";
import { Suspense } from "react";
import { MeguribiHeader } from "@/components/MeguribiHeader";
import { GoogleAnalytics } from "@/components/GoogleAnalytics";
import { getMetadataBaseUrl } from "@/lib/siteUrl";

const base = getMetadataBaseUrl();

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
      </head>
      <body className="bg-black">
        <Suspense>
          <GoogleAnalytics />
        </Suspense>
        <script
          dangerouslySetInnerHTML={{
            __html: `if("serviceWorker"in navigator){window.addEventListener("load",function(){navigator.serviceWorker.register("/sw.js")})}`,
          }}
        />
        <MeguribiHeader />
        <div className="min-h-screen text-slate-50">{children}</div>
        <footer className="border-t border-white/5 bg-black px-4 py-6 text-center text-[11px] text-white/30">
          <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-center gap-x-4 gap-y-1">
            <span>&copy; {new Date().getFullYear()} めぐりび (MEGRIBI)</span>
            <a href="/disclaimer" className="underline hover:text-white/60">
              免責事項・ご利用にあたって
            </a>
          </div>
          <p className="mt-2">
            本サービスは各相席ブランドの公式サービスではありません。表示データは参考値です。
          </p>
        </footer>
      </body>
    </html>
  );
}
