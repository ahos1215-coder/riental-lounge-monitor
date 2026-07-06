"use client";

import { BRAND_DISPLAY_LABEL, buildStoreMapsUrl, type BrandId } from "@/app/config/stores";
import { sendEvent } from "@/lib/analytics";

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
 * ストアページに無かった「行く」導線。地図（主導線）と公式サイト（副導線）を並べる。
 * めぐりびは各ブランドと無関係の非公式サードパーティサービスであり、これは予約導線・
 * アフィリエイトリンクではない（ReservationLinkCard と同じ立て付け）。
 */
export function GoThereActionRow({
  storeSlug,
  storeLabel,
  areaLabel,
  mapsQueryBase,
  brand,
  officialUrl,
}: {
  storeSlug: string;
  storeLabel: string;
  areaLabel: string;
  mapsQueryBase: string;
  brand: BrandId;
  officialUrl?: string | null;
}) {
  const mapsUrl = buildStoreMapsUrl({ mapsQueryBase, areaLabel, label: storeLabel });
  const officialBase = officialUrl || BRAND_OFFICIAL_URL[brand];
  const officialHref = buildUtmUrl(officialBase, {
    utm_source: "megribi",
    utm_medium: "referral",
    utm_campaign: "store_detail",
    utm_content: storeSlug,
  });
  const brandLabel = BRAND_DISPLAY_LABEL[brand];

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap gap-2">
        <a
          href={mapsUrl}
          target="_blank"
          rel="noopener noreferrer"
          onClick={() => sendEvent("store_map_click", { store_slug: storeSlug })}
          className="inline-flex min-h-11 flex-1 items-center justify-center gap-1.5 rounded-xl border border-emerald-500/30 bg-emerald-600/15 px-4 py-2 text-sm font-semibold text-emerald-100 transition hover:border-emerald-400/50 hover:bg-emerald-600/25"
        >
          地図でひらく <span aria-hidden>→</span>
        </a>
        <a
          href={officialHref}
          target="_blank"
          rel="nofollow noopener noreferrer"
          onClick={() => sendEvent("store_official_click", { store_slug: storeSlug })}
          className="inline-flex min-h-11 flex-1 items-center justify-center gap-1.5 rounded-xl border border-indigo-500/30 bg-indigo-600/15 px-4 py-2 text-sm font-semibold text-indigo-100 transition hover:border-indigo-400/50 hover:bg-indigo-600/25"
        >
          公式サイト <span aria-hidden>→</span>
        </a>
      </div>
      <p className="text-[10px] text-white/50">
        ※ リンク先は {brandLabel} 公式サイト・Google マップです。めぐりびは非公式の第三者サービスです。
      </p>
    </div>
  );
}
