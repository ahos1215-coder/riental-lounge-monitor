"use client";

import { StoreCard } from "@/components/StoreCard";
import { track } from "@/lib/analytics";
import { BRAND_DISPLAY_LABEL, type StoreMeta } from "../../config/stores";
import type { RelatedRealtimeMap } from "./storePageTypes";

type RelatedStoresSectionProps = {
  digestStores: StoreMeta[];
  relatedRealtime: RelatedRealtimeMap;
  relatedLoading: boolean;
  /** 現在表示中の店舗 slug（related_store_click の from 側）。 */
  fromSlug?: string;
};

export function RelatedStoresSection({
  digestStores,
  relatedRealtime,
  relatedLoading,
  fromSlug,
}: RelatedStoresSectionProps) {
  return (
    <section className="mx-auto w-full max-w-6xl space-y-3 px-4">
      <h2 className="text-sm font-semibold text-slate-100">ほかの店舗を見る</h2>
      <p className="text-[11px] text-slate-500">別店舗の人数・混雑の目安を、カードからすぐに比較できます。</p>
      <div className="grid gap-3 md:grid-cols-4">
        {digestStores.map((store, idx) => (
          <StoreCard
            key={store.slug}
            slug={store.slug}
            label={store.label}
            brandLabel={BRAND_DISPLAY_LABEL[store.brand]}
            brand={store.brand}
            capacity={store.capacity}
            areaLabel={store.areaLabel}
            isHighlight={idx === 0}
            stats={relatedRealtime[store.slug]?.stats}
            sparklinePoints={relatedRealtime[store.slug]?.sparkline}
            sparklineMen={relatedRealtime[store.slug]?.sparklineMen}
            sparklineWomen={relatedRealtime[store.slug]?.sparklineWomen}
            isLoading={relatedLoading && !relatedRealtime[store.slug]}
            onNavigate={() =>
              // 2026-08-26 計測レビュー対応: 識別子を store_slug（遷移先）+ from_slug（元の店舗）に
              // 統一（従来 from/to で、他イベントの store_slug と揃っていなかった）。
              track("related_store_click", { store_slug: store.slug, from_slug: fromSlug ?? "" })
            }
          />
        ))}
      </div>
    </section>
  );
}
