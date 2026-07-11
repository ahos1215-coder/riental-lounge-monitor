"use client";

import Script from "next/script";
import { usePathname, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import {
  GA_MEASUREMENT_ID,
  analyticsEnabled,
  sendPageView,
  syncDevOptOutFromQuery,
} from "@/lib/analytics";

/**
 * gtag.js を読み込み SPA 遷移を追跡する。以下のすべてを満たす時だけ GA を有効化する:
 *  - 測定 ID が設定されている
 *  - 本番ホスト（meguribi.jp / www.meguribi.jp）である
 *  - 開発者オプトアウト（?dev=1 由来の localStorage フラグ）がされていない
 * それ以外（localhost・Vercel プレビュー・開発者端末）では何もレンダーせず gtag をロードしない。
 */
export function GoogleAnalytics() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [enabled, setEnabled] = useState(false);

  useEffect(() => {
    // 1) 先に開発者オプトアウトを解決する（?dev=1/0 を localStorage に反映し、オプトアウト中は
    //    gtag ロード前に ga-disable を立てる）。これはどの beacon よりも前に走る＝レースセーフ。
    syncDevOptOutFromQuery(searchParams);
    // 2) 本番ホスト かつ 未オプトアウト かつ 測定 ID あり の時だけ GA を有効化する。
    const on = analyticsEnabled();
    setEnabled(on);
    // 3) 有効時のみ SPA 遷移のページビューを送る（初回 PV は下の config スクリプトが送る）。
    if (on) {
      const url = pathname + (searchParams?.toString() ? `?${searchParams}` : "");
      sendPageView(url);
    }
  }, [pathname, searchParams]);

  if (!GA_MEASUREMENT_ID || !enabled) return null;

  return (
    <>
      <Script
        src={`https://www.googletagmanager.com/gtag/js?id=${GA_MEASUREMENT_ID}`}
        strategy="afterInteractive"
      />
      <Script id="ga4-init" strategy="afterInteractive">
        {`
          window.dataLayer = window.dataLayer || [];
          function gtag(){dataLayer.push(arguments);}
          gtag('js', new Date());
          gtag('config', '${GA_MEASUREMENT_ID}');
        `}
      </Script>
    </>
  );
}
