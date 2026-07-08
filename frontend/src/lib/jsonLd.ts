/**
 * JSON-LD (application/ld+json) 埋め込み用のシリアライズヘルパー。
 * "<" を "<" にエスケープし、</script> による XSS/レンダリング崩れを防ぐ。
 */
export function serializeJsonLd(data: unknown): string {
  return JSON.stringify(data).replace(/</g, "\\u003c");
}

/** BreadcrumbList の1階層分。item は絶対URL文字列を渡す。 */
export type BreadcrumbItem = {
  name: string;
  item: string;
};

/**
 * schema.org BreadcrumbList を組み立てる共通ヘルパー。
 * 呼び出し側は「ホーム→中間階層→現在地」の順で name/item を渡すだけでよい。
 * position は配列インデックスから自動採番する。
 */
export function buildBreadcrumbList(items: BreadcrumbItem[]): Record<string, unknown> {
  return {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: items.map((entry, idx) => ({
      "@type": "ListItem",
      position: idx + 1,
      name: entry.name,
      item: entry.item,
    })),
  };
}

/** buildNightClubJsonLd に渡す店舗情報。store/[id]/page.tsx の StoreMeta と同じ形状のサブセット。 */
export type NightClubStoreInput = {
  name: string;
  url: string;
  regionLabel: string;
  areaLabel: string;
  lat?: number | null;
  lon?: number | null;
};

/**
 * 店舗の regionLabel / areaLabel から addressCountry (ISO 3166-1 alpha-2) を推定する。
 * 現状カタログ上の海外店舗は「海外」region かつ areaLabel に国名を含む形（例: gangnam の
 * "韓国・江南"）で表現されているため、それを手掛かりに判定する。該当なしは日本国内 "JP" 扱い。
 * 新しい海外拠点が増えた場合はここに国名判定を追加する。
 */
function inferAddressCountry(store: Pick<NightClubStoreInput, "regionLabel" | "areaLabel">): string {
  if (store.regionLabel === "海外") {
    if (store.areaLabel.includes("韓国")) return "KR";
    // 今後 海外 region に他国舗が増えた場合のフォールバック（国名不明のため "海外" 扱いのみ）。
    return "KR";
  }
  return "JP";
}

/**
 * schema.org NightClub（LocalBusiness）JSON-LD を組み立てる共通ヘルパー。
 * addressCountry は store の regionLabel/areaLabel から内部で自動判定する
 * （海外店舗＝韓国・江南 は "KR"、それ以外は "JP"）。
 */
export function buildNightClubJsonLd(store: NightClubStoreInput): Record<string, unknown> {
  const localBusiness: Record<string, unknown> = {
    "@context": "https://schema.org",
    "@type": "NightClub",
    name: store.name,
    address: {
      "@type": "PostalAddress",
      addressRegion: store.regionLabel,
      addressLocality: store.areaLabel,
      addressCountry: inferAddressCountry(store),
    },
    url: store.url,
  };
  if (store.lat != null && store.lon != null) {
    localBusiness.geo = {
      "@type": "GeoCoordinates",
      latitude: store.lat,
      longitude: store.lon,
    };
  }
  return localBusiness;
}
