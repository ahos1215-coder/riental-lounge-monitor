/**
 * 予約・公式サイトリンクカード（UTM 計測付き）
 * アフィリエイト ASP に切り替える場合は `href` を書き換えるだけでよい。
 *
 * utm_source / utm_medium は固定。
 * utm_campaign は呼び出し元ページ種別（"daily_report" / "weekly_report" / "store_detail"）を渡す。
 * utm_content は店舗 slug。
 */

type Props = {
  storeName: string;
  storeSlug: string;
  /** 公式サイト or アフィリエイトリンク。未指定時は Oriental Lounge 公式サイトを使用 */
  reservationUrl?: string;
  utmCampaign?: "daily_report" | "weekly_report" | "store_detail";
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
  utmCampaign = "store_detail",
}: Props) {
  const officialUrl = reservationUrl ?? "https://oriental-lounge.com/";
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
          <p className="text-xs font-medium text-indigo-300/70">公式サイトで詳細を確認</p>
          <p className="mt-0.5 text-sm text-white/70">{storeName} の最新情報・営業時間</p>
        </div>
        <a
          href={href}
          target="_blank"
          rel="noopener noreferrer sponsored"
          className="shrink-0 rounded-xl border border-indigo-500/30 bg-indigo-600/20 px-4 py-2 text-sm font-semibold text-indigo-200 transition hover:bg-indigo-600/30 hover:text-white"
        >
          公式サイトへ →
        </a>
      </div>
      <p className="mt-2 text-[10px] text-white/25">
        ※ リンク先は Oriental Lounge 公式サイトです
      </p>
    </div>
  );
}
