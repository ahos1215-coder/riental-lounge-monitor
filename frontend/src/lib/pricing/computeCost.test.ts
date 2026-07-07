import { describe, expect, it } from "vitest";

import { NAGASAKI_PRICING } from "@/data/pricing/nagasaki";
import {
  computeStayCost,
  computeStayPlans,
  minutesToTimeLabel,
  normalizeStayMinutes,
  timeToMinutes,
  validateStayWindow,
} from "./computeCost";

const pricing = NAGASAKI_PRICING;

function minutesFor(hhmm: string): number {
  return normalizeStayMinutes(hhmm, pricing.openTime);
}

describe("timeToMinutes / minutesToTimeLabel", () => {
  it("round-trips a normal time", () => {
    expect(timeToMinutes("18:00")).toBe(18 * 60);
    expect(minutesToTimeLabel(18 * 60)).toBe("18:00");
  });

  it("handles overnight minutes (24:00-29:59) and labels them as 00:00-05:59", () => {
    expect(timeToMinutes("24:00")).toBe(24 * 60);
    expect(minutesToTimeLabel(24 * 60)).toBe("00:00");
    expect(minutesToTimeLabel(25 * 60 + 30)).toBe("01:30");
  });
});

describe("normalizeStayMinutes", () => {
  it("keeps evening times as-is", () => {
    expect(minutesFor("22:00")).toBe(22 * 60);
  });

  it("shifts early-morning times (before open) to the next-day range", () => {
    expect(minutesFor("02:00")).toBe(26 * 60);
    expect(minutesFor("00:00")).toBe(24 * 60);
  });
});

describe("computeStayCost - weekday 2h from 22:00", () => {
  // 公式サイト実測値: 22:00〜24:00 バンドは平日¥660/10分（発注時の共有表は¥550だったが
  // 生HTML確認の結果ズレがあり、公式サイトの実測値を正としている。詳細は
  // frontend/src/data/pricing/nagasaki.ts の先頭コメント参照）。
  it("charges 12 units x ¥660 = ¥7920 for men, no charges toggles", () => {
    const entry = minutesFor("22:00");
    const exit = minutesFor("24:00");
    const result = computeStayCost(pricing, "weekday", entry, exit, {
      appCheckin: false,
      solo: false,
    });

    expect(result.unitsBreakdown).toHaveLength(1);
    expect(result.unitsBreakdown[0].units).toBe(12);
    expect(result.unitsBreakdown[0].unitPrice).toBe(660);
    expect(result.unitsBreakdown[0].subtotal).toBe(7920);
    expect(result.boundaries).toHaveLength(0);

    // charges: entry charge applies since appCheckin=false
    expect(result.charges).toEqual([{ label: "チャージ", amount: 550 }]);
    expect(result.total).toBe(7920 + 550);
  });
});

describe("computeStayCost - span crossing 24:00 mixes band prices", () => {
  it("weekday 23:00-01:00 mixes ¥660 (22-24) and ¥770 (24-Close)", () => {
    const entry = minutesFor("23:00");
    const exit = minutesFor("01:00");
    const result = computeStayCost(pricing, "weekday", entry, exit, {
      appCheckin: true,
      solo: false,
    });

    // 23:00-24:00 = 6 units @660, 24:00-01:00 = 6 units @770
    const bandA = result.unitsBreakdown.find((r) => r.band.label === "22:00〜24:00");
    const bandB = result.unitsBreakdown.find((r) => r.band.label === "24:00〜Close");
    expect(bandA?.units).toBe(6);
    expect(bandA?.unitPrice).toBe(660);
    expect(bandA?.subtotal).toBe(3960);
    expect(bandB?.units).toBe(6);
    expect(bandB?.unitPrice).toBe(770);
    expect(bandB?.subtotal).toBe(4620);

    expect(result.boundaries).toHaveLength(1);
    expect(result.boundaries[0].atLabel).toBe("00:00");
    expect(result.boundaries[0].oldPrice).toBe(660);
    expect(result.boundaries[0].newPrice).toBe(770);

    // appCheckin=true => entry charge waived, shown as 0
    expect(result.charges).toEqual([
      { label: "チャージ（アプリチェックインで無料）", amount: 0 },
    ]);
    expect(result.total).toBe(3960 + 4620);
  });
});

describe("computeStayCost - weekend rates", () => {
  it("uses weekend prices for the same window", () => {
    const entry = minutesFor("20:00");
    const exit = minutesFor("22:00");
    const result = computeStayCost(pricing, "weekend", entry, exit, {
      appCheckin: true,
      solo: false,
    });
    expect(result.unitsBreakdown).toHaveLength(1);
    expect(result.unitsBreakdown[0].unitPrice).toBe(600);
    expect(result.unitsBreakdown[0].units).toBe(12);
    expect(result.total).toBe(600 * 12);
  });
});

describe("computeStayCost - charges", () => {
  it("adds both entry charge and single charge when solo and no app checkin", () => {
    const entry = minutesFor("18:00");
    const exit = minutesFor("19:00");
    const result = computeStayCost(pricing, "weekday", entry, exit, {
      appCheckin: false,
      solo: true,
    });
    expect(result.charges).toEqual([
      { label: "チャージ", amount: 550 },
      { label: "シングルチャージ（お一人様利用）", amount: 1100 },
    ]);
    // 18:00-19:00 = 6 units @ 440 (Open〜20:00 band)
    expect(result.unitsBreakdown[0].unitPrice).toBe(440);
    expect(result.unitsBreakdown[0].units).toBe(6);
    expect(result.total).toBe(440 * 6 + 550 + 1100);
  });

  it("rounds up partial units (25 minutes = 3 units)", () => {
    const entry = minutesFor("18:00");
    const exit = entry + 25;
    const result = computeStayCost(pricing, "weekday", entry, exit, {
      appCheckin: true,
      solo: false,
    });
    expect(result.unitsBreakdown[0].units).toBe(3);
  });
});

describe("women's pricing", () => {
  it("is flat ¥0 regardless of time", () => {
    expect(pricing.women.price).toBe(0);
  });
});

describe("validateStayWindow", () => {
  it("rejects entry before 18:00", () => {
    const r = validateStayWindow(pricing, timeToMinutes("17:00"), timeToMinutes("19:00"));
    expect(r.ok).toBe(false);
  });

  it("rejects exit before/equal entry", () => {
    const entry = minutesFor("22:00");
    const r = validateStayWindow(pricing, entry, entry);
    expect(r.ok).toBe(false);
  });

  it("rejects exit after 06:00 (30:00)", () => {
    const entry = minutesFor("22:00");
    const r = validateStayWindow(pricing, entry, timeToMinutes("30:30"));
    expect(r.ok).toBe(false);
  });

  it("accepts a valid overnight window", () => {
    const entry = minutesFor("23:00");
    const exit = minutesFor("02:00");
    const r = validateStayWindow(pricing, entry, exit);
    expect(r.ok).toBe(true);
  });
});

describe("computeStayPlans", () => {
  it("returns 1h/2h/3h/close options with increasing totals", () => {
    const entry = minutesFor("22:00");
    const plans = computeStayPlans(pricing, "weekday", entry, {
      appCheckin: true,
      solo: false,
    });
    const labels = plans.map((p) => p.label);
    expect(labels).toEqual(["1時間", "2時間", "3時間", "クローズまで"]);
    // totals should be non-decreasing as duration grows
    for (let i = 1; i < plans.length; i += 1) {
      expect(plans[i].result.total).toBeGreaterThanOrEqual(plans[i - 1].result.total);
    }
  });

  it("caps the 'close' plan at closeTime even if entry is late", () => {
    const entry = minutesFor("05:00"); // 29:00
    const plans = computeStayPlans(pricing, "weekday", entry, {
      appCheckin: true,
      solo: false,
    });
    const closePlan = plans.find((p) => p.label === "クローズまで");
    expect(closePlan?.exitLabel).toBe("06:00");
  });
});
