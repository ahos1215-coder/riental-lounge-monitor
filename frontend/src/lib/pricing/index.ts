// frontend/src/lib/pricing/index.ts
//
// 店舗slug -> 料金テーブルのレジストリ。オリエンタルラウンジ日本国内36店舗に対応
// （frontend/src/data/pricing/raw.ts が単一の生データソース）。
// 未対応の店舗（相席屋・海外店舗・sapporo_agなど）は null を返す
// （UI 側は null なら何も描画しない = CostSimulatorCard は非表示になる）。

import { ORIENTAL_PRICING_REGISTRY } from "@/data/pricing/build";
import type { PricingTable } from "@/data/pricing/types";

/** 店舗slugに対応する料金テーブルを返す。未対応の店舗は null。 */
export function getStorePricing(slug: string | null | undefined): PricingTable | null {
  if (!slug) return null;
  return ORIENTAL_PRICING_REGISTRY[slug.toLowerCase()] ?? null;
}

export type { PricingTable, PricingBand, PricingCharges, SoloRate, DayType } from "@/data/pricing/types";
