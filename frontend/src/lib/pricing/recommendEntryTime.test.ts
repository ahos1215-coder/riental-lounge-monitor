import { describe, expect, it } from "vitest";

import { ORIENTAL_PRICING_REGISTRY } from "@/data/pricing/build";
import { NAGASAKI_PRICING } from "@/data/pricing/nagasaki";
import { recommendEntryTime, type ForecastSlotLike } from "./recommendEntryTime";

const pricing = NAGASAKI_PRICING;

/** 15分刻みの予測スロットを生成（19:00〜05:00、valueFnは「openTime基準の分」を受け取る） */
function buildForecastSeries(
  womenFn: (minute: number) => number,
  menFn: (minute: number) => number,
): ForecastSlotLike[] {
  const slots: ForecastSlotLike[] = [];
  // 19:00 (1140) 〜 29:00 (翌05:00, 1740)
  for (let m = 19 * 60; m <= 29 * 60; m += 15) {
    const h = Math.floor(m / 60) % 24;
    const min = m % 60;
    slots.push({
      label: `${h.toString().padStart(2, "0")}:${min.toString().padStart(2, "0")}`,
      menActual: null,
      womenActual: null,
      menForecast: menFn(m),
      womenForecast: womenFn(m),
    });
  }
  return slots;
}

describe("recommendEntryTime", () => {
  it("(a) early-heavy night: never recommends before 19:30", () => {
    // 女性が19:00にピーク(10人)でその後急減 → それでも候補下限19:30を守る
    const series = buildForecastSeries(
      (m) => Math.max(0, 10 - (m - 19 * 60) / 20), // 19:00=10人, 22:20頃に0人
      () => 6,
    );
    const rec = recommendEntryTime(series, pricing);
    expect(rec).not.toBeNull();
    expect(rec!.entryMinutes).toBeGreaterThanOrEqual(19 * 60 + 30);
    // 減少が急なので最善は19:30そのもの（除外境界に張り付く）
    expect(rec!.entryMinutes).toBe(19 * 60 + 30);
  });

  it("(a2) early_caution: flat night avoids pre-20:30 candidates", () => {
    // 一晩じゅう完全に同じ人数 → 20:30以前はearly_caution(0.8)で不利になり、
    // 20:30以降の同点はタイブレーク（安いバンド→早い時刻）で20:30が選ばれる
    const series = buildForecastSeries(
      () => 8,
      () => 8,
    );
    const rec = recommendEntryTime(series, pricing);
    expect(rec).not.toBeNull();
    expect(rec!.entryMinutes).toBe(20 * 60 + 30);
    expect(rec!.entryDisplayLabel).toBe("20:30");
  });

  it("(b) late-peak night (nagasaki-like): recommends ~23:30", () => {
    // 21:00頃から増え始めて翌01:00にピーク(8人)になる夜 → 上限24:00の直前が最善
    const women = (m: number) => {
      const peakAt = 25 * 60; // 翌01:00
      const start = 21 * 60;
      if (m < start) return 1;
      if (m <= peakAt) return 1 + ((m - start) / (peakAt - start)) * 7; // 1→8人へ線形増加
      return Math.max(0, 8 - (m - peakAt) / 30);
    };
    const series = buildForecastSeries(women, () => 5);
    const rec = recommendEntryTime(series, pricing);
    expect(rec).not.toBeNull();
    // 最終候補スロットは23:45 → 表示は30分切り下げで23:30ごろ
    expect(rec!.entryDisplayLabel).toBe("23:30");
    expect(rec!.rising).toBe(true);
    expect(rec!.reasons.some((r) => r.includes("女性は増加中"))).toBe(true);
  });

  it("(c) quiet night triggers floor fallback + note", () => {
    // 夜のピーク女性2人 → 全候補が閑散フィルタで0点でも最善スロット+静かな夜の注記を返す
    const series = buildForecastSeries(
      () => 2,
      () => 3,
    );
    const rec = recommendEntryTime(series, pricing);
    expect(rec).not.toBeNull();
    expect(rec!.quietNight).toBe(true);
    expect(rec!.reasons.some((r) => r.includes("静か"))).toBe(true);
  });

  it("(d) tie-break prefers the cheaper price band", () => {
    // 21:30〜23:45で女性数がほぼ同じ高原状態 → スコア同点圏では
    // 安いバンド(20:00〜22:00=¥550)に入る21:30側が選ばれる
    const women = (m: number) => {
      if (m < 21 * 60 + 30) return 1;
      if (m <= 25 * 60 + 30) return 8; // 21:30〜翌01:30 フラットな高原
      return 1;
    };
    const series = buildForecastSeries(women, () => 8);
    const rec = recommendEntryTime(series, pricing);
    expect(rec).not.toBeNull();
    // 21:30 は 20:00〜22:00 バンド(平日¥550)。22:00以降(¥660)より安い
    expect(rec!.entryMinutes).toBe(21 * 60 + 30);
    expect(rec!.entryDisplayLabel).toBe("21:30");
  });

  it("returns null when the series has no forecast at all", () => {
    const series: ForecastSlotLike[] = [
      { label: "21:00", menActual: 5, womenActual: 4, menForecast: null, womenForecast: null },
      { label: "22:00", menActual: 6, womenActual: 5, menForecast: null, womenForecast: null },
    ];
    expect(recommendEntryTime(series, pricing)).toBeNull();
  });

  it("returns null for an empty series", () => {
    expect(recommendEntryTime([], pricing)).toBeNull();
  });
});

// ============================================================================
// 全36店舗ロールアウト: openH が異なる店舗での候補ウィンドウのスケーリング検証
// 「開店+90分より前を除外」ルールが店舗のopenTimeに正しく追従することを確認する。
// ============================================================================

describe("recommendEntryTime - candidate window scales with the store's openTime", () => {
  it("18:00-open store (nagasaki): candidates never before 19:30 (=18:00+90min)", () => {
    expect(pricing.openTime).toBe("18:00");
    // 19:00にピークで急減する夜 → 除外境界の19:30に張り付くはず
    const series = buildForecastSeries(
      (m) => Math.max(0, 10 - (m - 19 * 60) / 20),
      () => 6,
    );
    const rec = recommendEntryTime(series, pricing);
    expect(rec).not.toBeNull();
    expect(rec!.entryMinutes).toBeGreaterThanOrEqual(19 * 60 + 30);
    expect(rec!.entryMinutes).toBe(19 * 60 + 30);
  });

  it("19:00-open store (namba): candidates never before 20:30 (=19:00+90min)", () => {
    const namba = ORIENTAL_PRICING_REGISTRY.namba;
    expect(namba.openTime).toBe("19:00");

    // namba用の予測系列（19:00始まり、女性が19:00にピークして急減する夜）
    const slots: ForecastSlotLike[] = [];
    for (let m = 19 * 60; m <= 29 * 60; m += 15) {
      const h = Math.floor(m / 60) % 24;
      const min = m % 60;
      const women = Math.max(0, 10 - (m - 19 * 60) / 20);
      slots.push({
        label: `${h.toString().padStart(2, "0")}:${min.toString().padStart(2, "0")}`,
        menActual: null,
        womenActual: null,
        menForecast: 6,
        womenForecast: women,
      });
    }

    const rec = recommendEntryTime(slots, namba);
    expect(rec).not.toBeNull();
    // 19:00+90分=20:30が下限。18:00基準のnagasakiと違い19:30ではなく20:30になることを確認
    expect(rec!.entryMinutes).toBeGreaterThanOrEqual(20 * 60 + 30);
    expect(rec!.entryMinutes).toBe(20 * 60 + 30);
  });

  it("17:00-open store (umeda_ag): candidates never before 18:30 (=17:00+90min)", () => {
    const umedaAg = ORIENTAL_PRICING_REGISTRY.umeda_ag;
    expect(umedaAg.openTime).toBe("17:00");

    const slots: ForecastSlotLike[] = [];
    for (let m = 17 * 60; m <= 29 * 60; m += 15) {
      const h = Math.floor(m / 60) % 24;
      const min = m % 60;
      const women = Math.max(0, 10 - (m - 17 * 60) / 20);
      slots.push({
        label: `${h.toString().padStart(2, "0")}:${min.toString().padStart(2, "0")}`,
        menActual: null,
        womenActual: null,
        menForecast: 6,
        womenForecast: women,
      });
    }

    const rec = recommendEntryTime(slots, umedaAg);
    expect(rec).not.toBeNull();
    expect(rec!.entryMinutes).toBeGreaterThanOrEqual(17 * 60 + 90);
    expect(rec!.entryMinutes).toBe(17 * 60 + 90); // 18:30
  });
});
