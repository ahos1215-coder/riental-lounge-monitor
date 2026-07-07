// frontend/src/data/pricing/build.ts
//
// RawStorePricing（raw.ts の生データ）を、UI・計算エンジンが使う PricingTable
// 形式へ変換する純粋関数群。長崎店プロトタイプ時代の "HH:MM" 文字列表現
// （24:00以降は 24:00〜59:59 でオーバーナイトを表す）を踏襲しつつ、
// 全36店舗ぶんの openH/closeH/バンド数のばらつきを一般化して吸収する。
//
// ■ 生HTML直読み方式について
// WebFetch（要約AI経由）は同じ料金表ページに対して複数回異なる集計結果を返す
// （バンド対応のズレ・VIP行との混同など）ことが長崎店データ検証時に確認された。
// そのため raw.ts の全データは `.dl-table-inner` 配下の <dt>/<dd> を機械的に
// 抽出する方式で取得しており、本ファイルはその生データを解釈するだけで
// 独自の推測は行わない（推測が必要な箇所は「開店直後の空白バンド」のみ、
// かつコメント・assumptionNotes で明示する）。

import { getStoreMetaBySlugStrict, buildStoreFullName } from "@/app/config/stores";
import { PRICING_VERIFIED_AT, RAW_ORIENTAL_PRICING, type RawStorePricing } from "./raw";
import type { DayType, PricingBand, PricingTable } from "./types";

/** 24h+表記の時（0〜59を許容）を "HH:MM" へ。分は常に00（バンド境界は必ず正時のため）。 */
function hToLabel(h: number): string {
  return `${h.toString().padStart(2, "0")}:00`;
}

/**
 * raw.ts の startH/endH は「24時以降は24-30のように連番で表す」店舗もあれば、
 * 渋谷店の「6時〜Close」のように素直な「6」（当日6時の意味ではなく、開店より
 * 前の時刻=翌日側の6時を意味する）で書かれている店舗もある。全36店舗の
 * バンド列が「直前バンドのendHと次バンドのstartHが連続している」ことを
 * 2026-07-08 に検証済み（唯一の不連続は nagoya_ag の開店直後の空白バンドのみ、
 * 別途 fillOpeningGap で対応）。そのため次のルールが安全に成立する:
 *   値 < 基準openH なら、その値は「翌日側」を意味するとみなし +24 する。
 * 基準openH には「両曜日タイプのうち早い方」を使う（例: 天満店は週末openH=17
 * を基準にする。18を基準にすると週末の17時が「前日」扱いの誤判定になる）。
 */
function normalizeH(h: number, baseOpenH: number): number {
  return h < baseOpenH ? h + 24 : h;
}

/**
 * 生バンド配列を PricingBand[] へ変換する（時刻は上記ルールで正規化した24h+表記）。
 *
 * 「開店直後の空白バンド」対応（nagoya_ag 等）:
 *   公式サイトの価格表が openH より遅い時刻から始まる場合（例: 19時開店だが
 *   最初のバンドが「20時〜22時」から）、openH〜最初のバンド開始までの間は
 *   明示レートが存在しない。2026-07-08 に nagoya_ag の生HTMLを再確認し、
 *   実際に「19時〜20時」の行が存在しないことを確認済み。公式に「¥0」という
 *   記載も無いため、¥0扱いにすると安全側（安く見積もる）を逸脱し実損害の
 *   リスクがある。オーナー指示により「最初に掲載されているバンドの単価を
 *   暫定適用する」方針とし、この関数が openH からの合成バンドを1本追加する。
 *   この暫定措置は呼び出し元（buildPricingTable）で assumptionNotes に記録し、
 *   UIのフッターにも表示する。
 *
 *   なお「Open〜20時」のように公式ラベル自体が「Open」を使っているバンドは、
 *   曜日タイプによって実際の開店時刻が異なっても（例: 天満店の週末17時開店）
 *   そのバンド1本でカバーされる設計なので、空白バンド扱いにはしない
 *   （= 最も早い openH を基準にバンドの start を作るので、両曜日タイプとも
 *   自然にこのバンドでカバーされる）。
 */
function normalizeBands(raw: RawStorePricing, baseOpenH: number): PricingBand[] {
  const bands: PricingBand[] = raw.bands.map((b) => ({
    label: b.label,
    start: hToLabel(normalizeH(b.startH, baseOpenH)),
    end: hToLabel(normalizeH(b.endH, baseOpenH)),
    weekday: b.weekday,
    weekend: b.weekend,
  }));

  const first = raw.bands[0];
  if (first && first.startH > raw.openH) {
    const gapLabel = `Open〜${first.startH}時`;
    bands.unshift({
      label: gapLabel,
      start: hToLabel(baseOpenH),
      end: hToLabel(normalizeH(first.startH, baseOpenH)),
      // 最初に掲載されているバンドの単価をそのまま暫定適用（¥0にしない）
      weekday: first.weekday,
      weekend: first.weekend,
    });
  } else if (bands.length > 0) {
    // "Open〜XX時" のような動的ラベルのバンドは、週末の方が早く開店する場合
    // （天満店など）に備えて start を baseOpenH（=両曜日タイプのうち早い方）
    // まで front-fill しておく。これにより findBandForMinute が週末の
    // 早い時間帯でも正しくこのバンドを見つけられる。
    bands[0] = { ...bands[0], start: hToLabel(baseOpenH) };
  }

  return bands;
}

/** その店舗が「開店直後の空白バンド」補完を必要とするか（UIフッター注記の判定用） */
function hasOpeningGapAssumption(raw: RawStorePricing): boolean {
  const first = raw.bands[0];
  return !!first && first.startH > raw.openH;
}

/**
 * 曜日タイプ別の実際の開店時刻を決定する。
 * ほとんどの店舗は raw.openH がそのまま両曜日タイプの開店時刻だが、
 * 天満店のように週末だけ早く開店する店舗は openHWeekend で上書きされる
 * （2026-07-08 に全36店舗の「営業時間」セクションを生HTMLで再確認済み）。
 */
function computeOpenTimeByDayType(raw: RawStorePricing): Record<DayType, string> {
  const weekdayOpen = hToLabel(raw.openH);
  const weekendOpen = hToLabel(raw.openHWeekend ?? raw.openH);
  return { weekday: weekdayOpen, weekend: weekendOpen };
}

/**
 * 曜日タイプ別の実際の閉店時刻を決定する。
 *
 * raw.closeH は「営業時間」セクション（公式サイトの stance-time-wrap、価格表とは
 * 別セクション）から取得した平日の閉店時刻であり、これを平日側の正とする。
 * raw.closeHWeekend が明示されていればそれを週末側の正とする
 * （2026-07-08 に全36店舗の「営業時間」セクションを生HTMLで再確認し、
 * 平日・週末で閉店時刻が異なる11店舗を特定・記録した。詳細は raw.ts 各店舗の
 * コメント参照）。closeHWeekend 省略時は raw.closeH と同一とみなす。
 *
 * 例: 渋谷店は raw.closeH=5（平日 18:00〜05:00）, closeHWeekend=7（週末 18:00〜07:00）。
 * weekdayClose="29:00"（翌05:00）, weekendClose="31:00"（翌07:00）となる。
 */
function computeCloseTimeByDayType(raw: RawStorePricing): Record<DayType, string> {
  const weekdayClose = hToLabel(raw.closeH + 24);
  const weekendClose = hToLabel((raw.closeHWeekend ?? raw.closeH) + 24);
  return { weekday: weekdayClose, weekend: weekendClose };
}

const WEEKEND_RULE_TEXT =
  "金・土曜日および祝日前は週末料金が適用されます。年末年始・GW・お盆などの期間も週末料金となります。";

const WOMEN_NOTE = "食べ放題・飲み放題ともに¥0（一部有料の商品もございます）";

const SOLO_RATE_SOURCE_URL = "https://oriental-lounge.com/";

/** RawStorePricing 1件を PricingTable へ変換する。 */
export function buildPricingTable(raw: RawStorePricing): PricingTable {
  // バンド境界の「翌日側」判定基準には、両曜日タイプのうち早い方の開店時刻を使う
  // （例: 天満店は週末openH=17を基準にしないと、17時が「前日」誤判定になる）。
  const baseOpenH = Math.min(raw.openH, raw.openHWeekend ?? raw.openH);

  const bands = normalizeBands(raw, baseOpenH);
  const openTimeByDayType = computeOpenTimeByDayType(raw);
  const closeTimeByDayType = computeCloseTimeByDayType(raw);

  // openTime/closeTime は表示・UI選択肢の範囲決定に使う「両曜日タイプの最大範囲」。
  const openTime =
    timeLabelToMinutes(openTimeByDayType.weekend) <= timeLabelToMinutes(openTimeByDayType.weekday)
      ? openTimeByDayType.weekend
      : openTimeByDayType.weekday;
  const closeTime =
    timeLabelToMinutes(closeTimeByDayType.weekend) >= timeLabelToMinutes(closeTimeByDayType.weekday)
      ? closeTimeByDayType.weekend
      : closeTimeByDayType.weekday;

  const meta = getStoreMetaBySlugStrict(raw.slug);
  const storeName = meta ? buildStoreFullName(meta) : `オリエンタルラウンジ ${raw.slug}`;

  const assumptionNotes: string[] = [];
  if (hasOpeningGapAssumption(raw)) {
    const first = raw.bands[0];
    assumptionNotes.push(
      `開店(${raw.openH}:00)〜${first.startH}:00 は公式サイトに明示バンドが無いため、最初に掲載されている「${first.label}」の単価を暫定適用しています。`,
    );
  }

  return {
    storeSlug: raw.slug,
    storeName,
    unitMinutes: 10,
    openTime,
    closeTime,
    openTimeByDayType,
    closeTimeByDayType,
    bands,
    soloRate: {
      weekday: raw.soloRate.weekday,
      weekend: raw.soloRate.weekend,
      sourceUrl: SOLO_RATE_SOURCE_URL,
    },
    charges: raw.charges,
    women: {
      price: 0,
      note: WOMEN_NOTE,
    },
    weekendRule: WEEKEND_RULE_TEXT,
    sourceUrl: raw.sourceUrl,
    verifiedAt: PRICING_VERIFIED_AT,
    ...(assumptionNotes.length > 0 ? { assumptionNotes } : {}),
  };
}

function timeLabelToMinutes(hhmm: string): number {
  const [h, m] = hhmm.split(":").map(Number);
  return h * 60 + m;
}

/** 全36店舗ぶんの PricingTable レジストリ（slug -> table）。モジュール読み込み時に一度だけ構築する。 */
export const ORIENTAL_PRICING_REGISTRY: Record<string, PricingTable> = Object.fromEntries(
  Object.entries(RAW_ORIENTAL_PRICING).map(([slug, raw]) => [slug, buildPricingTable(raw)]),
);
