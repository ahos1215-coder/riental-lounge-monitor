"use client";

import Script from "next/script";
import { usePathname, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import {
  GA_MEASUREMENT_ID,
  analyticsEnabled,
  sendPageView,
  syncDevOptOutFromQuery,
} from "@/lib/analytics";

/**
 * 純粋関数: 今回の effect 実行でPVを送るべきか。
 * 「GA有効」かつ「pathname が前回送信時と異なる」時だけ true（＝クエリだけの変化では false）。
 * コンポーネント本体から切り出してユニットテストする（レンダリング全体は重いため）。
 */
export function shouldSendPageView(input: {
  enabled: boolean;
  pathname: string;
  lastSentPath: string | null;
}): boolean {
  return input.enabled && input.lastSentPath !== input.pathname;
}

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
  // 2026-08-26 計測レビュー対応: PVは pathname の変化"だけ"で送る。以前は effect の依存配列に
  // searchParams も入っていたため、(a) /reports の検索1文字ごとの router.replace、
  // (b) /compare の ?stores= 変更、(c) /store/[id] が mount 直後に自動付与する ?store= の
  // router.replace（一覧/エリア/トップ/検索エンジン経由の流入すべてが2PVになっていた）で
  // PVが水増しされていた。同一 pathname では2度目以降を送らない、という明示ガードで止める
  // （クエリだけの変化を専用イベントに変換する必要はない＝意味のある操作には既に個別イベントがある）。
  const lastSentPathRef = useRef<string | null>(null);

  useEffect(() => {
    // 1) 先に開発者オプトアウトを解決する（?dev=1/0 を localStorage に反映し、オプトアウト中は
    //    gtag ロード前に ga-disable を立てる）。これはどの beacon よりも前に走る＝レースセーフ。
    //    searchParams はこの effect の依存配列には入れない（下記コメント）が、pathname が
    //    変わった時点でのクエリを読めば実用上十分（?dev=1 は通常フルロードでの初回訪問で来る）。
    syncDevOptOutFromQuery(searchParams);
    // 2) 本番ホスト かつ 未オプトアウト かつ 測定 ID あり の時だけ GA を有効化する。
    const on = analyticsEnabled();
    setEnabled(on);
    // 3) 有効時のみ SPA 遷移のページビューを送る（初回 PV は下の config スクリプトが送る。
    //    この effect の初回実行時にも sendPageView は呼ばれるが、その時点では <Script id="ga4-init">
    //    がまだマウント/ロードされておらず window.gtag は未定義なので gtag() ラッパーが no-op になり
    //    二重送信しない——この初回レースは検証済みの既存設計であり壊さない）。
    //    pathname が前回送信時と同じ（＝クエリだけが変わった）場合は送らない。
    if (shouldSendPageView({ enabled: on, pathname, lastSentPath: lastSentPathRef.current })) {
      lastSentPathRef.current = pathname;
      const url = pathname + (searchParams?.toString() ? `?${searchParams}` : "");
      sendPageView(url);
    }
    // 意図的に pathname のみに依存させる。searchParams を依存に入れると query-only の変化の
    // たびに再実行されPVが水増しされる（上記コメント参照）。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname]);

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
