import { describe, expect, it } from "vitest";

import { ORIENTAL_PRICING_REGISTRY } from "@/data/pricing/build";
import { AISEKIYA_PRICING_REGISTRY } from "@/data/pricing/aisekiyaBuild";
import {
  aisekiyaUnitPrice,
  computeAisekiyaStayCost,
  computeAisekiyaStayPlans,
  computeStayCost,
  computeStayPlans,
  minutesToTimeLabel,
  normalizeStayMinutes,
  timeToMinutes,
  unitPriceAtMinute,
  validateStayWindow,
} from "./computeCost";

const pricing = ORIENTAL_PRICING_REGISTRY.nagasaki;

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

describe("computeStayCost - weekday 2h from 22:00 (nagasaki)", () => {
  // 公式サイト実測値: 22:00〜24:00 バンドは相席 平日¥660/10分（発注時の共有表は¥550だったが
  // 生HTML確認の結果ズレがあり、公式サイトの実測値を正としている。詳細は
  // frontend/src/data/pricing/raw.ts の先頭コメント参照）。
  it("max = 12 units x ¥660, min = 12 units x ¥220, both + entry charge", () => {
    const entry = minutesFor("22:00");
    const exit = minutesFor("24:00");
    const result = computeStayCost(pricing, "weekday", entry, exit, {
      appCheckin: false,
      solo: false,
    });

    expect(result.totalUnits).toBe(12);
    expect(result.unitsBreakdown).toHaveLength(1);
    expect(result.unitsBreakdown[0].units).toBe(12);
    expect(result.unitsBreakdown[0].unitPrice).toBe(660);
    expect(result.unitsBreakdown[0].subtotal).toBe(7920);
    expect(result.boundaries).toHaveLength(0);

    // charges: entry charge applies since appCheckin=false
    expect(result.charges).toEqual([{ label: "チャージ", amount: 550 }]);
    // 上限=ずっと相席 / 下限=相席なし(12×¥220)。チャージは両方に乗る
    expect(result.maxTotal).toBe(7920 + 550);
    expect(result.minTotal).toBe(12 * 220 + 550);
  });
});

describe("computeStayCost - span crossing 24:00 mixes band prices (nagasaki)", () => {
  it("weekday 23:00-01:00 mixes ¥660 (22-24) and ¥770 (24-Close)", () => {
    const entry = minutesFor("23:00");
    const exit = minutesFor("01:00");
    const result = computeStayCost(pricing, "weekday", entry, exit, {
      appCheckin: true,
      solo: false,
    });

    // 23:00-24:00 = 6 units @660, 24:00-01:00 = 6 units @770
    const bandA = result.unitsBreakdown.find((r) => r.band.label === "22時〜24時");
    const bandB = result.unitsBreakdown.find((r) => r.band.label === "24時〜Close");
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
    expect(result.maxTotal).toBe(3960 + 4620);
    // 下限は時間帯に関係なく全12ユニット×¥220（相席なし単価は深夜も同額）
    expect(result.minTotal).toBe(12 * 220);
  });
});

describe("computeStayCost - weekend rates (nagasaki)", () => {
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
    expect(result.maxTotal).toBe(600 * 12);
    // 相席なし単価(¥220)は平日・週末同額なので下限は曜日タイプに依存しない
    expect(result.minTotal).toBe(12 * 220);
  });
});

describe("computeStayCost - charges (nagasaki)", () => {
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
    // チャージ類は上限・下限の両方に同額で乗る
    expect(result.maxTotal).toBe(440 * 6 + 550 + 1100);
    expect(result.minTotal).toBe(220 * 6 + 550 + 1100);
  });

  it("rounds up partial units (25 minutes = 3 units) for both bounds", () => {
    const entry = minutesFor("18:00");
    const exit = entry + 25;
    const result = computeStayCost(pricing, "weekday", entry, exit, {
      appCheckin: true,
      solo: false,
    });
    expect(result.totalUnits).toBe(3);
    expect(result.unitsBreakdown[0].units).toBe(3);
    expect(result.minTotal).toBe(3 * 220);
  });

  it("min bound: 2h stay = 12 x ¥220 + charges", () => {
    const entry = minutesFor("21:00");
    const exit = minutesFor("23:00");
    const result = computeStayCost(pricing, "weekday", entry, exit, {
      appCheckin: false,
      solo: true,
    });
    expect(result.minTotal).toBe(12 * 220 + 550 + 1100);
    expect(result.minTotal).toBeLessThan(result.maxTotal);
  });
});

describe("women's pricing", () => {
  it("is flat ¥0 regardless of time", () => {
    expect(pricing.women.price).toBe(0);
  });
});

describe("validateStayWindow (nagasaki)", () => {
  it("rejects entry before 18:00", () => {
    const r = validateStayWindow(pricing, "weekday", timeToMinutes("17:00"), timeToMinutes("19:00"));
    expect(r.ok).toBe(false);
  });

  it("rejects exit before/equal entry", () => {
    const entry = minutesFor("22:00");
    const r = validateStayWindow(pricing, "weekday", entry, entry);
    expect(r.ok).toBe(false);
  });

  it("rejects exit after 06:00 (30:00)", () => {
    const entry = minutesFor("22:00");
    const r = validateStayWindow(pricing, "weekday", entry, timeToMinutes("30:30"));
    expect(r.ok).toBe(false);
  });

  it("accepts a valid overnight window", () => {
    const entry = minutesFor("23:00");
    const exit = minutesFor("02:00");
    const r = validateStayWindow(pricing, "weekday", entry, exit);
    expect(r.ok).toBe(true);
  });
});

describe("computeStayPlans (nagasaki)", () => {
  it("returns 1h/2h/3h/close options with increasing totals", () => {
    const entry = minutesFor("22:00");
    const plans = computeStayPlans(pricing, "weekday", entry, {
      appCheckin: true,
      solo: false,
    });
    const labels = plans.map((p) => p.label);
    expect(labels).toEqual(["1時間", "2時間", "3時間", "クローズまで"]);
    // totals should be non-decreasing as duration grows (both bounds)
    for (let i = 1; i < plans.length; i += 1) {
      expect(plans[i].result.maxTotal).toBeGreaterThanOrEqual(plans[i - 1].result.maxTotal);
      expect(plans[i].result.minTotal).toBeGreaterThanOrEqual(plans[i - 1].result.minTotal);
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

// ============================================================================
// 全36店舗ロールアウト: 多様な店舗での追加検証（手計算した金額をアサートする）
// ============================================================================

describe("computeStayCost - shibuya (high-rate, day-type-varying close, null band)", () => {
  const shibuya = ORIENTAL_PRICING_REGISTRY.shibuya;

  it("weekend 22:00-24:00 (2h) = 12 x ¥1100 (手計算: 12*1100=13200)", () => {
    const entry = normalizeStayMinutes("22:00", shibuya.openTime);
    const exit = normalizeStayMinutes("24:00", shibuya.openTime);
    const result = computeStayCost(shibuya, "weekend", entry, exit, { appCheckin: true, solo: false });
    expect(result.totalUnits).toBe(12);
    expect(result.unitsBreakdown).toHaveLength(1);
    expect(result.unitsBreakdown[0].unitPrice).toBe(1100);
    expect(result.maxTotal).toBe(12 * 1100);
  });

  it("weekend stay crossing into the weekday-null '6時〜Close' band (05:30-06:30) prices at ¥1200", () => {
    // 渋谷店は週末のみ 06:00〜07:00 も営業（平日はnullバンド=到達しない）。
    // 05:30入店で1h滞在=6ユニット、うち05:30-06:00は「24時〜6時」バンド(¥1200)、
    // 06:00-06:30は「6時〜Close」バンド(週末のみ、¥1200)。同額なので境界(boundaries)は出ない。
    const entry = normalizeStayMinutes("05:30", shibuya.openTime); // = 29:30
    const exit = normalizeStayMinutes("06:30", shibuya.openTime); // = 30:30
    const result = computeStayCost(shibuya, "weekend", entry, exit, { appCheckin: true, solo: false });
    expect(result.totalUnits).toBe(6);
    // 手計算: 6 units x ¥1200 = 7200
    expect(result.maxTotal).toBe(6 * 1200);
  });

  it("weekday validateStayWindow rejects exit past the true weekday close (05:00)", () => {
    // 渋谷店は平日 18:00〜05:00（週末は18:00〜07:00）。平日に05:30退店を試みると
    // closeTimeByDayType.weekday=29:00(=05:00)を超えるため弾かれるべき
    // （バンド自体の「24時〜6時」の見た目のendHは30:00=06:00まであるが、
    // 平日の実閉店は05:00で先に切れる）。
    const entry = normalizeStayMinutes("23:00", shibuya.openTime);
    const exit = normalizeStayMinutes("05:30", shibuya.openTime);
    const r = validateStayWindow(shibuya, "weekday", entry, exit);
    expect(r.ok).toBe(false);
  });

  it("weekend validateStayWindow accepts exit up to the true weekend close (07:00)", () => {
    const entry = normalizeStayMinutes("23:00", shibuya.openTime);
    const exit = normalizeStayMinutes("07:00", shibuya.openTime);
    const r = validateStayWindow(shibuya, "weekend", entry, exit);
    expect(r.ok).toBe(true);
  });

  it("weekday unitPriceAtMinute returns null once past the true weekday close", () => {
    // 06:00(=30:00)は平日には存在しない時間帯（平日は05:00閉店）
    const minute = normalizeStayMinutes("06:00", shibuya.openTime);
    expect(unitPriceAtMinute(shibuya, "weekday", minute)).toBeNull();
  });
});

describe("computeStayCost - nagoya_ag (19:00-open with opening-gap fill)", () => {
  const nagoyaAg = ORIENTAL_PRICING_REGISTRY.nagoya_ag;

  it("openTime is 19:00 and a synthetic Open〜20時 gap-fill band exists at the 20時〜22時 rate", () => {
    expect(nagoyaAg.openTime).toBe("19:00");
    expect(nagoyaAg.bands[0].label).toContain("Open");
    expect(nagoyaAg.bands[0].start).toBe("19:00");
    expect(nagoyaAg.bands[0].end).toBe("20:00");
    // 公式サイトに明示バンドが無いため、最初に掲載されている「20時〜22時」の単価を暫定適用
    expect(nagoyaAg.bands[0].weekday).toBe(660);
    expect(nagoyaAg.bands[0].weekend).toBe(770);
    expect(nagoyaAg.assumptionNotes?.length).toBeGreaterThan(0);
  });

  it("weekday 19:00-20:00 (gap window) bills at the borrowed ¥660 rate, never ¥0/NaN", () => {
    const entry = normalizeStayMinutes("19:00", nagoyaAg.openTime);
    const exit = normalizeStayMinutes("20:00", nagoyaAg.openTime);
    const result = computeStayCost(nagoyaAg, "weekday", entry, exit, { appCheckin: true, solo: false });
    expect(result.totalUnits).toBe(6);
    // 手計算: 6 units x ¥660 = 3960（¥0にならないことを明示的に確認）
    expect(result.maxTotal).toBe(6 * 660);
    expect(result.maxTotal).toBeGreaterThan(0);
    expect(Number.isNaN(result.maxTotal)).toBe(false);
  });

  it("weekend 19:30-22:30 (3h, crosses gap into 20時〜22時 and 22時〜24時) mixes rates correctly", () => {
    const entry = normalizeStayMinutes("19:30", nagoyaAg.openTime);
    const exit = normalizeStayMinutes("22:30", nagoyaAg.openTime);
    const result = computeStayCost(nagoyaAg, "weekend", entry, exit, { appCheckin: true, solo: false });
    // 19:30-20:00 = 3 units @770(gap-fill), 20:00-22:00 = 12 units @770, 22:00-22:30 = 3 units @880
    // 手計算: 3*770 + 12*770 + 3*880 = 2310 + 9240 + 2640 = 14190
    expect(result.maxTotal).toBe(3 * 770 + 12 * 770 + 3 * 880);
    expect(result.totalUnits).toBe(18);
  });
});

describe("computeStayCost - umeda_ag (17:00-open, early opening)", () => {
  const umedaAg = ORIENTAL_PRICING_REGISTRY.umeda_ag;

  it("openTime is 17:00 with no gap-fill needed (Open〜20時 band starts exactly at 17:00)", () => {
    expect(umedaAg.openTime).toBe("17:00");
    expect(umedaAg.bands[0].start).toBe("17:00");
    expect(umedaAg.assumptionNotes).toBeUndefined();
  });

  it("weekday 17:00-20:00 (3h, the wide first band) = 18 x ¥660 (手計算: 18*660=11880)", () => {
    const entry = normalizeStayMinutes("17:00", umedaAg.openTime);
    const exit = normalizeStayMinutes("20:00", umedaAg.openTime);
    const result = computeStayCost(umedaAg, "weekday", entry, exit, { appCheckin: true, solo: false });
    expect(result.totalUnits).toBe(18);
    expect(result.unitsBreakdown).toHaveLength(1);
    expect(result.maxTotal).toBe(18 * 660);
  });

  it("solo (男性1名) rate is ¥330/10min, unlike nagasaki's ¥220", () => {
    expect(umedaAg.soloRate.weekday).toBe(330);
    expect(umedaAg.soloRate.weekend).toBe(330);
  });
});

describe("computeStayCost - kokura (day-type-varying close via last-band extension, no null band)", () => {
  const kokura = ORIENTAL_PRICING_REGISTRY.kokura;

  it("closeTimeByDayType differs: weekday 02:00, weekend 05:00", () => {
    expect(kokura.closeTimeByDayType.weekday).toBe("26:00"); // 翌02:00
    expect(kokura.closeTimeByDayType.weekend).toBe("29:00"); // 翌05:00
  });

  it("weekday validateStayWindow rejects exit past 02:00", () => {
    const entry = normalizeStayMinutes("23:00", kokura.openTime);
    const exit = normalizeStayMinutes("03:00", kokura.openTime);
    const r = validateStayWindow(kokura, "weekday", entry, exit);
    expect(r.ok).toBe(false);
  });

  it("weekend 03:00-05:00 (2h, past the last band's own end=24:00-26:00 but within true close) extends the last band's rate", () => {
    // 小倉店の価格表は「24時〜Close」バンド1本(startH24,endH26)しか無いが、
    // 週末の実閉店は05:00(=29:00)。価格表のendH(26=02:00)を超えても
    // 実閉店までは最終バンドの単価(¥880)を延長適用する（Close延長ルール）。
    const entry = normalizeStayMinutes("03:00", kokura.openTime); // = 27:00
    const exit = normalizeStayMinutes("05:00", kokura.openTime); // = 29:00
    const result = computeStayCost(kokura, "weekend", entry, exit, { appCheckin: true, solo: false });
    expect(result.totalUnits).toBe(12);
    // 手計算: 12 units x ¥880 = 10560（延長された最終バンドの単価）
    expect(result.maxTotal).toBe(12 * 880);
  });

  it("weekend validateStayWindow accepts exit exactly at the extended true close (05:00)", () => {
    const entry = normalizeStayMinutes("23:00", kokura.openTime);
    const exit = normalizeStayMinutes("05:00", kokura.openTime);
    const r = validateStayWindow(kokura, "weekend", entry, exit);
    expect(r.ok).toBe(true);
  });
});

// ============================================================================
// 相席屋（6店舗）: フラット10分単価モデルの追加検証
// ============================================================================

describe("aisekiya pricing registry", () => {
  it("includes exactly the 5 operating aisekiya stores", () => {
    expect(Object.keys(AISEKIYA_PRICING_REGISTRY).sort()).toEqual(
      ["ay_chiba", "ay_ikebukuro", "ay_shibuya", "ay_ueno", "ay_yokohama"].sort(),
    );
  });

  it("every store uses model:'aisekiya' and the chain-wide ¥650/¥750 rate unless flagged otherwise", () => {
    for (const [slug, table] of Object.entries(AISEKIYA_PRICING_REGISTRY)) {
      expect(table.model, slug).toBe("aisekiya");
      expect(table.josekiRate.weekday, slug).toBe(650);
      expect(table.josekiRate.weekend, slug).toBe(750);
      expect(table.charges.entry, slug).toBe(550);
      expect(table.nonJosekiRate, slug).toBe(0);
      expect(table.women.price, slug).toBe(0);
    }
  });
});

describe("computeAisekiyaStayCost - ay_shibuya (uniform 17:00-29:00 hours, no waiver-method quirks)", () => {
  const shibuya = AISEKIYA_PRICING_REGISTRY.ay_shibuya;

  it("weekday 2h stay ENTIRELY before 22:00 (20:00-22:00) = 12 x ¥650 = ¥7,800, + charge when app off", () => {
    // 20:00入店・22:00退店。各ユニットの開始は20:00〜21:50（=分 1200〜1310）で
    // すべて22:00(1320)より前のため、深夜加算は一切かからない。
    const entry = normalizeStayMinutes("20:00", shibuya.openTime);
    const exit = normalizeStayMinutes("22:00", shibuya.openTime);
    const result = computeAisekiyaStayCost(shibuya, "weekday", entry, exit, { appCheckin: false });
    expect(result.totalUnits).toBe(12);
    expect(result.normalUnits).toBe(12);
    expect(result.lateNightUnits).toBe(0);
    expect(result.unitPrice).toBe(650);
    expect(result.staySubtotal).toBe(7800);
    expect(result.charges).toEqual([{ label: "チャージ", amount: 550 }]);
    expect(result.total).toBe(7800 + 550);
  });

  it("weekend 2h stay ENTIRELY before 22:00 (20:00-22:00) = 12 x ¥750 = ¥9,000, app checkin waives the charge", () => {
    const entry = normalizeStayMinutes("20:00", shibuya.openTime);
    const exit = normalizeStayMinutes("22:00", shibuya.openTime);
    const result = computeAisekiyaStayCost(shibuya, "weekend", entry, exit, { appCheckin: true });
    expect(result.totalUnits).toBe(12);
    expect(result.lateNightUnits).toBe(0);
    expect(result.unitPrice).toBe(750);
    expect(result.staySubtotal).toBe(9000);
    expect(result.charges).toEqual([{ label: "チャージ（アプリチェックインで無料）", amount: 0 }]);
    expect(result.total).toBe(9000);
  });

  it("weekday stay SPANNING 22:00 (21:30-23:30) mixes ¥650 and ¥715 (手計算: 3*650 + 9*715 = 1950 + 6435 = 8385)", () => {
    // 21:30入店・23:30退店=120分=12ユニット。開始分 1290,1300,1310 が22:00前(3本)、
    // 1320,1330,...,1400 が22:00以降(9本)。深夜単価=650*1.1=715。
    const entry = normalizeStayMinutes("21:30", shibuya.openTime);
    const exit = normalizeStayMinutes("23:30", shibuya.openTime);
    const result = computeAisekiyaStayCost(shibuya, "weekday", entry, exit, { appCheckin: true });
    expect(result.totalUnits).toBe(12);
    expect(result.normalUnits).toBe(3);
    expect(result.lateNightUnits).toBe(9);
    expect(result.unitPrice).toBe(650);
    expect(result.lateNightUnitPrice).toBe(715);
    expect(result.normalSubtotal).toBe(3 * 650);
    expect(result.lateNightSubtotal).toBe(9 * 715);
    expect(result.staySubtotal).toBe(1950 + 6435);
    expect(result.total).toBe(8385); // appCheckin=trueなのでチャージ¥0
  });

  it("weekend stay SPANNING 22:00 (21:30-23:30) mixes ¥750 and ¥825 (手計算: 3*750 + 9*825 = 2250 + 7425 = 9675)", () => {
    const entry = normalizeStayMinutes("21:30", shibuya.openTime);
    const exit = normalizeStayMinutes("23:30", shibuya.openTime);
    const result = computeAisekiyaStayCost(shibuya, "weekend", entry, exit, { appCheckin: true });
    expect(result.normalUnits).toBe(3);
    expect(result.lateNightUnits).toBe(9);
    expect(result.lateNightUnitPrice).toBe(825);
    expect(result.staySubtotal).toBe(2250 + 7425);
    expect(result.total).toBe(9675);
  });

  it("stay ENTIRELY at/after 22:00 (22:00-24:00) applies the surcharge to all units (手計算 weekday: 12*715=8580)", () => {
    // 22:00入店・24:00退店=12ユニット、開始分 1320..1430 すべて22:00以降。
    const entry = normalizeStayMinutes("22:00", shibuya.openTime);
    const exit = normalizeStayMinutes("24:00", shibuya.openTime);
    const wd = computeAisekiyaStayCost(shibuya, "weekday", entry, exit, { appCheckin: true });
    expect(wd.normalUnits).toBe(0);
    expect(wd.lateNightUnits).toBe(12);
    expect(wd.total).toBe(12 * 715);
    const we = computeAisekiyaStayCost(shibuya, "weekend", entry, exit, { appCheckin: true });
    expect(we.total).toBe(12 * 825); // 9900
  });

  it("post-midnight units are still surcharged (24:00-01:00 = 6 units @¥715 weekday)", () => {
    // 深夜0:00〜1:00。openTime基準では 1440〜1500分。すべて1320以降なので深夜単価。
    const entry = normalizeStayMinutes("24:00", shibuya.openTime);
    const exit = normalizeStayMinutes("01:00", shibuya.openTime);
    const result = computeAisekiyaStayCost(shibuya, "weekday", entry, exit, { appCheckin: true });
    expect(result.totalUnits).toBe(6);
    expect(result.lateNightUnits).toBe(6);
    expect(result.total).toBe(6 * 715);
  });

  it("rounds up partial units (25 minutes = 3 units), matching the oriental 10-min rounding rule", () => {
    const entry = normalizeStayMinutes("20:00", shibuya.openTime);
    const exit = entry + 25;
    const result = computeAisekiyaStayCost(shibuya, "weekday", entry, exit, { appCheckin: true });
    expect(result.totalUnits).toBe(3);
    expect(result.staySubtotal).toBe(3 * 650);
  });

  it("late-night unit price is josekiRate×1.1 rounded, NOT a reuse of the tax-included field", () => {
    // ¥650×1.1=¥715, ¥750×1.1=¥825。税込参考値と数値は一致するが別物として独立計算。
    expect(aisekiyaUnitPrice(650, true)).toBe(715);
    expect(aisekiyaUnitPrice(750, true)).toBe(825);
    expect(aisekiyaUnitPrice(650, false)).toBe(650);
    expect(aisekiyaUnitPrice(750, false)).toBe(750);
  });

  it("women's rate is flat ¥0 regardless of day type", () => {
    expect(shibuya.women.price).toBe(0);
  });
});

describe("computeAisekiyaStayPlans - ay_shibuya", () => {
  const shibuya = AISEKIYA_PRICING_REGISTRY.ay_shibuya;

  it("returns 1h/2h/3h/close options with non-decreasing totals", () => {
    const entry = normalizeStayMinutes("20:00", shibuya.openTime);
    const plans = computeAisekiyaStayPlans(shibuya, "weekday", entry, { appCheckin: true });
    const labels = plans.map((p) => p.label);
    expect(labels).toEqual(["1時間", "2時間", "3時間", "クローズまで"]);
    for (let i = 1; i < plans.length; i += 1) {
      expect(plans[i].result.total).toBeGreaterThanOrEqual(plans[i - 1].result.total);
    }
  });

  it("a peak-plan chip that crosses 22:00 reflects the surcharge (21:00 entry, 2h plan)", () => {
    // 21:00入店の2時間プラン=21:00〜23:00=12ユニット。開始分 1260,1270,1280,1290,1300,1310
    // が22:00前(6本)、1320..1370が22:00以降(6本)。手計算: 6*650 + 6*715 = 3900 + 4290 = 8190。
    const entry = normalizeStayMinutes("21:00", shibuya.openTime);
    const plans = computeAisekiyaStayPlans(shibuya, "weekday", entry, { appCheckin: true });
    const twoHour = plans.find((p) => p.label === "2時間");
    expect(twoHour?.result.normalUnits).toBe(6);
    expect(twoHour?.result.lateNightUnits).toBe(6);
    expect(twoHour?.result.total).toBe(6 * 650 + 6 * 715);
  });
});

describe("computeAisekiyaStayCost - ay_ueno (widest weekend-bucket hours: Sat/Sun open earliest at 15:00)", () => {
  const ueno = AISEKIYA_PRICING_REGISTRY.ay_ueno;

  it("openTimeByDayType.weekend is 15:00 (widest across Fri/Sat/Sun/holiday/holiday-eve)", () => {
    expect(ueno.openTimeByDayType.weekend).toBe("15:00");
    expect(ueno.openTimeByDayType.weekday).toBe("17:00");
  });

  it("weekend 1h stay from 22:00 = 6 x ¥825 (all late-night; 手計算: 6*825=4950)", () => {
    // 22:00〜23:00の6ユニットはすべて22:00以降＝深夜単価¥825（旧テストの¥4,500は加算前の誤り）。
    const entry = normalizeStayMinutes("22:00", ueno.openTime);
    const exit = normalizeStayMinutes("23:00", ueno.openTime);
    const result = computeAisekiyaStayCost(ueno, "weekend", entry, exit, { appCheckin: true });
    expect(result.totalUnits).toBe(6);
    expect(result.lateNightUnits).toBe(6);
    expect(result.total).toBe(4950);
  });

  it("weekend early stay entirely before 22:00 (18:00-20:00) stays at ¥750 flat = ¥9,000", () => {
    const entry = normalizeStayMinutes("18:00", ueno.openTime);
    const exit = normalizeStayMinutes("20:00", ueno.openTime);
    const result = computeAisekiyaStayCost(ueno, "weekend", entry, exit, { appCheckin: true });
    expect(result.lateNightUnits).toBe(0);
    expect(result.total).toBe(12 * 750);
  });
});

describe("computeAisekiyaStayCost - ay_chiba (LINE@ waiver; surcharge now applied like every store)", () => {
  const chiba = AISEKIYA_PRICING_REGISTRY.ay_chiba;

  it("bills ¥650 for a pre-22:00 window (20:00-22:00) — no surcharge on units before 22:00", () => {
    const entry = normalizeStayMinutes("20:00", chiba.openTime);
    const exit = normalizeStayMinutes("22:00", chiba.openTime);
    const result = computeAisekiyaStayCost(chiba, "weekday", entry, exit, { appCheckin: true });
    expect(result.lateNightUnits).toBe(0);
    expect(result.unitPrice).toBe(650);
    expect(result.staySubtotal).toBe(12 * 650);
  });

  it("still carries the Sunday hours/pricing-mismatch note (but the surcharge note is gone — surcharge is now computed)", () => {
    expect(chiba.assumptionNotes?.some((n) => n.includes("日曜日"))).toBe(true);
    // 加算は計算に反映済みなので「加算を含めていません」という受動的な注記は削除した
    expect(chiba.assumptionNotes?.some((n) => n.includes("加算を含めていません"))).toBe(false);
  });
});

describe("22:00+ 10% surcharge is applied in computation for every live aisekiya store (chain-wide)", () => {
  // 検証当初は千葉店固有の注記と誤認し、かつ本体金額に反映していなかった。
  // 現在は全店で「各ユニット開始が22:00以降なら×1.1」を計算に組み込んでいる。
  it("a 22:00-23:00 stay is surcharged (6 units @ josekiRate×1.1) at all 5 stores, both day types", () => {
    for (const [slug, table] of Object.entries(AISEKIYA_PRICING_REGISTRY)) {
      for (const dayType of ["weekday", "weekend"] as const) {
        const entry = normalizeStayMinutes("22:00", table.openTime);
        const exit = normalizeStayMinutes("23:00", table.openTime);
        const result = computeAisekiyaStayCost(table, dayType, entry, exit, { appCheckin: true });
        const expectedUnit = Math.round(table.josekiRate[dayType] * 1.1);
        expect(result.lateNightUnits, `${slug}/${dayType}`).toBe(6);
        expect(result.total, `${slug}/${dayType}`).toBe(6 * expectedUnit);
      }
    }
  });
});

describe("validateStayWindow works unchanged for aisekiya tables (brand-agnostic, PricingTableBase only)", () => {
  const shibuya = AISEKIYA_PRICING_REGISTRY.ay_shibuya;

  it("rejects entry before open (17:00)", () => {
    const r = validateStayWindow(shibuya, "weekday", timeToMinutes("16:00"), timeToMinutes("18:00"));
    expect(r.ok).toBe(false);
  });

  it("accepts a valid overnight window within 17:00-29:00", () => {
    const entry = normalizeStayMinutes("23:00", shibuya.openTime);
    const exit = normalizeStayMinutes("02:00", shibuya.openTime);
    const r = validateStayWindow(shibuya, "weekday", entry, exit);
    expect(r.ok).toBe(true);
  });
});

describe("minutesToTimeLabel / normalizeStayMinutes sanity check for aisekiya (shared utility, no aisekiya-specific behavior expected)", () => {
  it("round-trips like the oriental case", () => {
    expect(minutesToTimeLabel(17 * 60)).toBe("17:00");
    expect(minutesToTimeLabel(29 * 60)).toBe("05:00");
  });
});
