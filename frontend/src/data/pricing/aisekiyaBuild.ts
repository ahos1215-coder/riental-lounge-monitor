// frontend/src/data/pricing/aisekiyaBuild.ts
//
// AisekiyaRawStorePricing（aisekiyaRaw.ts の生データ）を、UI・計算エンジンが使う
// AisekiyaPricingTable 形式へ変換する純粋関数群。build.ts（オリエンタル用）と
// 同じ "HH:MM" 文字列表現（24:00以降は 24:00〜59:59 でオーバーナイトを表す）を
// 踏襲しているが、相席屋は時間帯バンドが無いフラット単価モデルのため、
// バンド生成ロジック（normalizeBands・開店直後ギャップ補完など）は不要。

import { getStoreMetaBySlugStrict, buildStoreFullName } from "@/app/config/stores";
import { AISEKIYA_PRICING_VERIFIED_AT, RAW_AISEKIYA_PRICING, type AisekiyaRawStorePricing } from "./aisekiyaRaw";
import type { AisekiyaPricingTable, DayType } from "./types";

/** 24h+表記の時（0〜59を許容）を "HH:MM" へ。分は常に00（相席屋の営業時間は全店正時区切り）。 */
function hToLabel(h: number): string {
  return `${h.toString().padStart(2, "0")}:00`;
}

function computeOpenTimeByDayType(raw: AisekiyaRawStorePricing): Record<DayType, string> {
  return { weekday: hToLabel(raw.openH), weekend: hToLabel(raw.openHWeekend) };
}

function computeCloseTimeByDayType(raw: AisekiyaRawStorePricing): Record<DayType, string> {
  return { weekday: hToLabel(raw.closeH), weekend: hToLabel(raw.closeHWeekend) };
}

function timeLabelToMinutes(hhmm: string): number {
  const [h, m] = hhmm.split(":").map(Number);
  return h * 60 + m;
}

const AISEKIYA_WEEKEND_RULE_TEXT =
  "高料金の対象: 金・土・日曜日・祝日・祝前日（オリエンタルラウンジとは異なり日曜日も高料金の対象です）";

const AISEKIYA_WOMEN_NOTE = "完全無料・時間無制限（食べ飲み放題込み、チャージ料金も無し）";

/** AisekiyaRawStorePricing 1件を AisekiyaPricingTable へ変換する。 */
export function buildAisekiyaPricingTable(raw: AisekiyaRawStorePricing): AisekiyaPricingTable {
  const openTimeByDayType = computeOpenTimeByDayType(raw);
  const closeTimeByDayType = computeCloseTimeByDayType(raw);

  // openTime/closeTime は表示・UI選択肢の範囲決定に使う「両曜日タイプの最大範囲」
  // （build.ts と同じ考え方）。
  const openTime =
    timeLabelToMinutes(openTimeByDayType.weekend) <= timeLabelToMinutes(openTimeByDayType.weekday)
      ? openTimeByDayType.weekend
      : openTimeByDayType.weekday;
  const closeTime =
    timeLabelToMinutes(closeTimeByDayType.weekend) >= timeLabelToMinutes(closeTimeByDayType.weekday)
      ? closeTimeByDayType.weekend
      : closeTimeByDayType.weekday;

  const meta = getStoreMetaBySlugStrict(raw.slug);
  const storeName = meta ? buildStoreFullName(meta) : `相席屋 ${raw.slug}`;

  const assumptionNotes = raw.assumptionNotes ? [...raw.assumptionNotes] : undefined;

  return {
    model: "aisekiya",
    storeSlug: raw.slug,
    storeName,
    unitMinutes: 10,
    openTime,
    closeTime,
    openTimeByDayType,
    closeTimeByDayType,
    josekiRate: raw.josekiRate,
    josekiRateTaxIncluded: raw.josekiRateTaxIncluded,
    nonJosekiRate: 0,
    charges: { entry: raw.chargeEntry },
    women: {
      price: 0,
      note: AISEKIYA_WOMEN_NOTE,
    },
    weekendRule: AISEKIYA_WEEKEND_RULE_TEXT,
    sourceUrl: raw.sourceUrl,
    verifiedAt: AISEKIYA_PRICING_VERIFIED_AT,
    ...(assumptionNotes ? { assumptionNotes } : {}),
  };
}

/**
 * 相席屋6店舗ぶんの AisekiyaPricingTable レジストリ（slug -> table）。
 * ay_niigata は2026-07-08時点で閉店済み（aisekiyaRaw.ts 冒頭コメント参照）のため
 * RAW_AISEKIYA_PRICING に収録しておらず、このレジストリにも含まれない
 * （getStorePricing は "ay_niigata" に対し null を返す）。
 */
export const AISEKIYA_PRICING_REGISTRY: Record<string, AisekiyaPricingTable> = Object.fromEntries(
  Object.entries(RAW_AISEKIYA_PRICING).map(([slug, raw]) => [slug, buildAisekiyaPricingTable(raw)]),
);
