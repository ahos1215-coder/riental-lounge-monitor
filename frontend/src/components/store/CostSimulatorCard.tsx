"use client";

import type { PricingTable } from "@/data/pricing/types";
import type { ForecastSlotLike } from "@/lib/pricing/recommendEntryTime";

import { AisekiyaCostSimulatorCard } from "./AisekiyaCostSimulatorCard";
import { OrientalCostSimulatorCard } from "./OrientalCostSimulatorCard";

type Props = {
  pricing: PricingTable;
  /** タイムライン系列（実測+予測）。「今夜の入店の目安」の算出に使う */
  series: ForecastSlotLike[];
  /** 今夜の予測が取得できているか（false なら例示ベースの表示にフォールバック） */
  hasForecast?: boolean;
};

/**
 * 料金の目安カード。pricing.model でオリエンタル（時間帯バンド制）と
 * 相席屋（フラット10分単価制・曜日区分も異なる）を振り分ける。
 * PreviewMainSection.tsx から getStorePricing(slug) の戻り値が null でない
 * ときだけ描画される（36店舗＋相席屋6店舗の計42店舗が対象。他ブランド・
 * データ未整備店舗は元々 pricing===null で非表示）。
 */
export function CostSimulatorCard({ pricing, series, hasForecast }: Props) {
  if (pricing.model === "aisekiya") {
    return <AisekiyaCostSimulatorCard pricing={pricing} series={series} hasForecast={hasForecast} />;
  }
  return <OrientalCostSimulatorCard pricing={pricing} series={series} hasForecast={hasForecast} />;
}
