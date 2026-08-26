"use client";

/**
 * 外部（ブランド公式サイト）リンクカード（UTM 計測付き）
 * めぐりびは各ブランドとは無関係の非公式サードパーティサービスであり、
 * このカードは予約導線・アフィリエイトリンクではない。
 *
 * utm_source / utm_medium は固定。
 * utm_campaign は呼び出し元ページ種別（"daily_report" / "weekly_report" / "store_detail"）を渡す。
 * utm_content は店舗 slug。
 *
 * 2026-08-26 計測レビュー対応: クリック計測がゼロだった盲点のひとつ（送客の実数が
 * 追えていなかった）。GA4 に official_site_click を発火する onClick を追加したため、
 * このファイル自体が client boundary になる必要があり "use client" を付けた
 * （呼び出し元の日報/週報ページは Server Component のまま変更していない）。
 *
 * 2026-08-26 計測レビューR2対応: official_site_click には露出分母が無く「表示されていない」のか
 * 「表示されたが押されない」のかを区別できなかった（レビュー§4-2）。このカード自体を
 * useExposureOnce で監視し、50%以上・1000ms以上表示されたら一度だけ official_site_view を送る。
 */

import { useCallback } from "react";
import { track } from "@/lib/analytics";
import { useExposureOnce } from "@/app/hooks/useExposureOnce";
import { BRAND_DISPLAY_LABEL, type BrandId } from "@/app/config/stores";

type Props = {
  storeName: string;
  storeSlug: string;
  /** ブランド公式サイトの URL。未指定時はブランドごとの既定 URL を使用 */
  reservationUrl?: string;
  /** ブランド（未指定は oriental）。リンク先とラベルを切り替える。 */
  brand?: BrandId;
  utmCampaign?: "daily_report" | "weekly_report" | "store_detail";
};

// ブランド別の公式サイト（reservationUrl 未指定時のフォールバック）
const BRAND_OFFICIAL_URL: Record<BrandId, string> = {
  oriental: "https://oriental-lounge.com/",
  aisekiya: "https://aiseki-ya.com/",
  jis: "https://oriental-lounge.com/",
};

function buildUtmUrl(base: string, params: Record<string, string>): string {
  const url = new URL(base);
  for (const [key, value] of Object.entries(params)) {
    url.searchParams.set(key, value);
  }
  return url.toString();
}

/**
 * official_site_click の GA4 パラメータを組み立てる純粋関数（テスト容易化のため export）。
 * destination_domain は officialUrl（UTM付与前のベースURL）のホスト名。href は毎回 UTM
 * クエリ付きで値が変わるため、集計しやすい安定した値としてホスト名だけを渡す。
 *
 * brand は analytics.ts（T1班のSSOT）の AnalyticsEventParamsByName 型では "oriental"|"aisekiya" の
 * 2値のみ（cost_sim_interact も同じ2値しか送っていない前例）。このカードの brand prop は
 * BrandId（"jis" を含む3値）を受け取りうるが、stores.json に brand="jis" の店舗は
 * 2026-08-26時点で0件のため、型上だけ存在する "jis" は "oriental" にフォールバックする。
 */
export function officialSiteClickParams(
  storeSlug: string,
  brand: BrandId,
  officialUrl: string,
): { store_slug: string; brand: "oriental" | "aisekiya"; destination_domain: string } {
  return {
    store_slug: storeSlug,
    brand: brand === "aisekiya" ? "aisekiya" : "oriental",
    destination_domain: new URL(officialUrl).hostname,
  };
}

export function ReservationLinkCard({
  storeName,
  storeSlug,
  reservationUrl,
  brand = "oriental",
  utmCampaign = "store_detail",
}: Props) {
  // reservationUrl という名前だが、実体はブランド公式サイトへの外部リンク（予約導線ではない）
  const officialUrl = reservationUrl ?? BRAND_OFFICIAL_URL[brand];
  const brandLabel = BRAND_DISPLAY_LABEL[brand];
  const href = buildUtmUrl(officialUrl, {
    utm_source: "megribi",
    utm_medium: "referral",
    utm_campaign: utmCampaign,
    utm_content: storeSlug,
  });

  // official_site_click と同じ brand 正規化（"jis" は型上だけ存在し、2値のみ送る）。
  const normalizedBrand: "oriental" | "aisekiya" = brand === "aisekiya" ? "aisekiya" : "oriental";
  const handleExpose = useCallback(() => {
    track("official_site_view", { store_slug: storeSlug, brand: normalizedBrand });
  }, [storeSlug, normalizedBrand]);
  const exposureRef = useExposureOnce<HTMLDivElement>(handleExpose);

  return (
    <div ref={exposureRef} className="rounded-2xl border border-indigo-500/20 bg-indigo-950/20 p-4">
      <div className="flex items-center justify-between gap-4">
        <div>
          <p className="text-xs font-medium text-indigo-300/70">外部サイトで詳細を確認</p>
          <p className="mt-0.5 text-sm text-white/70">{storeName} の最新情報・営業時間</p>
        </div>
        <a
          href={href}
          target="_blank"
          rel="nofollow noopener noreferrer"
          onClick={() => track("official_site_click", officialSiteClickParams(storeSlug, brand, officialUrl))}
          className="shrink-0 rounded-xl border border-indigo-500/30 bg-indigo-600/20 px-4 py-2 text-sm font-semibold text-indigo-200 transition hover:bg-indigo-600/30 hover:text-white"
        >
          外部サイトで確認 →
        </a>
      </div>
      <p className="mt-2 text-[10px] text-white/25">
        ※ リンク先は {brandLabel} 公式サイトです。めぐりびは非公式の第三者サービスです。
      </p>
    </div>
  );
}
