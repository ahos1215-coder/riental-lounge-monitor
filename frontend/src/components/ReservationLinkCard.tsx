/**
 * 外部（ブランド公式サイト）リンクカード（UTM 計測付き）
 * めぐりびは各ブランドとは無関係の非公式サードパーティサービスであり、
 * このカードは予約導線・アフィリエイトリンクではない。
 *
 * utm_source / utm_medium は固定。
 * utm_campaign は呼び出し元ページ種別（"daily_report" / "weekly_report" / "store_detail"）を渡す。
 * utm_content は店舗 slug。
 */

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

  return (
    <div className="rounded-2xl border border-indigo-500/20 bg-indigo-950/20 p-4">
      <div className="flex items-center justify-between gap-4">
        <div>
          <p className="text-xs font-medium text-indigo-300/70">外部サイトで詳細を確認</p>
          <p className="mt-0.5 text-sm text-white/70">{storeName} の最新情報・営業時間</p>
        </div>
        <a
          href={href}
          target="_blank"
          rel="nofollow noopener noreferrer"
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
