// frontend/src/lib/pricing/index.ts
//
// 店舗slug -> 料金テーブルのレジストリ。オリエンタルラウンジ日本国内36店舗
// （frontend/src/data/pricing/raw.ts）と相席屋の営業中5店舗
// （frontend/src/data/pricing/aisekiyaRaw.ts）の両方に対応する。
// 未対応の店舗（海外店舗・sapporo_ag など）は null を返す
// （UI 側は null なら何も描画しない = CostSimulatorCard は非表示になる）。

import { ORIENTAL_PRICING_REGISTRY } from "@/data/pricing/build";
import { AISEKIYA_PRICING_REGISTRY } from "@/data/pricing/aisekiyaBuild";
import type { PricingTable } from "@/data/pricing/types";

/** 両ブランドを統合したレジストリ（slugは重複しない前提。念のため相席屋を後勝ちにしている） */
const PRICING_REGISTRY: Record<string, PricingTable> = {
  ...ORIENTAL_PRICING_REGISTRY,
  ...AISEKIYA_PRICING_REGISTRY,
};

/** 店舗slugに対応する料金テーブルを返す。未対応の店舗は null。 */
export function getStorePricing(slug: string | null | undefined): PricingTable | null {
  if (!slug) return null;
  return PRICING_REGISTRY[slug.toLowerCase()] ?? null;
}

export type {
  PricingTable,
  PricingTableBase,
  OrientalPricingTable,
  AisekiyaPricingTable,
  AisekiyaCharges,
  PricingBand,
  PricingCharges,
  SoloRate,
  DayType,
} from "@/data/pricing/types";
