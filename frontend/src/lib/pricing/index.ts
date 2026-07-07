// frontend/src/lib/pricing/index.ts
//
// 店舗slug -> 料金テーブルのレジストリ。料金シミュレーターは今のところ長崎店のみの
// プロトタイプなので、他店舗は null を返す（UI 側は null なら何も描画しない）。
// 別店舗を追加する際は frontend/src/data/pricing/<slug>.ts を追加してここに登録する。

import { NAGASAKI_PRICING, type PricingTable } from "@/data/pricing/nagasaki";

const PRICING_REGISTRY: Partial<Record<string, PricingTable>> = {
  nagasaki: NAGASAKI_PRICING,
};

/** 店舗slugに対応する料金テーブルを返す。未対応の店舗は null。 */
export function getStorePricing(slug: string | null | undefined): PricingTable | null {
  if (!slug) return null;
  return PRICING_REGISTRY[slug.toLowerCase()] ?? null;
}

export type { PricingTable, PricingBand, PricingCharges, DayType } from "@/data/pricing/nagasaki";
