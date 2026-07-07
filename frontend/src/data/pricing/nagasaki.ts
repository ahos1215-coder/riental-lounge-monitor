// frontend/src/data/pricing/nagasaki.ts
//
// 長崎店（slug: nagasaki）の料金テーブル。全36店舗ロールアウトに伴い、
// 手動データの直書きから registry.ts（raw.ts + build.ts）由来の派生値へ変更した
// （単一ソース化。以前の手書き値と2026-07-08の生HTML再検証値は完全一致=差分ゼロ
// だったため、値そのものに変更は無い）。
//
// 既存テスト（computeCost.test.ts, recommendEntryTime.test.ts）が
// `NAGASAKI_PRICING` を直接importしているため、後方互換のためこのファイルは
// 残してある。新規コードは `@/lib/pricing`（getStorePricing）または
// `@/data/pricing/build`（ORIENTAL_PRICING_REGISTRY）経由で参照すること。

import { ORIENTAL_PRICING_REGISTRY } from "./build";

export const NAGASAKI_PRICING = ORIENTAL_PRICING_REGISTRY.nagasaki;

export type { DayType, PricingBand, PricingCharges, PricingTable, SoloRate } from "./types";
