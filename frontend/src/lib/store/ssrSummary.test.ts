import { describe, expect, it } from "vitest";

import { buildStoreSsrSummary, rollUpHourlyActuals } from "@/lib/store/ssrSummary";
import type { StoreSnapshot, TimeSeriesPoint } from "@/app/hooks/storePreviewSnapshot";

function pt(label: string, menActual: number | null, womenActual: number | null): TimeSeriesPoint {
  return { label, menActual, womenActual, menForecast: null, womenForecast: null };
}

function baseSnapshot(overrides: Partial<StoreSnapshot> = {}): StoreSnapshot {
  return {
    slug: "omiya",
    name: "オリエンタルラウンジ 大宮",
    area: "大宮",
    brand: "oriental",
    capacity: null,
    level: "データ取得済み",
    nowTotal: 40,
    nowMen: 18,
    nowWomen: 22,
    peakTimeLabel: "22:15",
    peakTotal: 58,
    peakMen: 30,
    peakWomen: 28,
    recommendation: "データ取得済み",
    forecastUpdatedLabel: "更新済み",
    series: [pt("19:00", 10, 12), pt("19:30", 12, 14), pt("20:00", 15, 18)],
    hasData: true,
    forecastStatus: "ok",
    latestActualTs: "2026-08-18T13:45:00.000Z", // JST 22:45
    peakTs: "2026-08-18T13:15:00.000Z",
    completedNight: false,
    ...overrides,
  };
}

describe("buildStoreSsrSummary", () => {
  it("データが無い時は null（空箱のHTMLを作らない）", () => {
    expect(buildStoreSsrSummary(null)).toBeNull();
    expect(buildStoreSsrSummary(undefined)).toBeNull();
    expect(buildStoreSsrSummary(baseSnapshot({ hasData: false }))).toBeNull();
  });

  it("オリエンタルは人数・男女比・ピーク・最終更新を出す", () => {
    const s = buildStoreSsrSummary(baseSnapshot());
    expect(s).not.toBeNull();
    expect(s!.storeName).toBe("オリエンタルラウンジ 大宮");
    expect(s!.areaLabel).toBe("大宮");
    expect(s!.occupancyLabel).toBe("店内の目安");
    expect(s!.occupancyValue).toBe("40名");
    expect(s!.genderStats).toEqual([
      { label: "男性", value: "18人" },
      { label: "女性", value: "22人" },
    ]);
    expect(s!.ratioText).toBe("男45% / 女55%");
    expect(s!.peakText).toBe("22:15（男性30名 / 女性28名）");
    // 「◯分前」ではなく JST の絶対時刻（ISRで焼いても嘘にならない）
    expect(s!.updatedText).toBe("22:45 時点");
  });

  it("相席屋は % のみ。人数（人／名）を一切出さない", () => {
    const s = buildStoreSsrSummary(
      baseSnapshot({
        slug: "ay_shibuya",
        name: "相席屋 渋谷店",
        area: "渋谷",
        brand: "aisekiya",
        capacity: 50,
        nowMen: 20,
        nowWomen: 25,
        nowTotal: 45,
        peakMen: 30,
        peakWomen: 35,
        peakTotal: 65,
      }),
    );
    expect(s).not.toBeNull();
    expect(s!.occupancyLabel).toBe("店内の埋まり具合");
    expect(s!.occupancyValue).toBe("約45%");
    expect(s!.genderStats).toEqual([
      { label: "男性", value: "40%" },
      { label: "女性", value: "50%" },
    ]);
    expect(s!.peakText).toBe("22:15（男性60% / 女性70%）");

    // 出力テキスト全体に人数の単位が混ざっていないこと
    const rendered = [
      s!.occupancyValue,
      ...s!.genderStats.map((g) => g.value),
      s!.peakText,
      ...s!.hourly.map((h) => h.value),
    ]
      .filter(Boolean)
      .join(" ");
    expect(rendered).not.toMatch(/人|名/);
  });

  it("ピーク時刻がプレースホルダ（--:--）なら出さない", () => {
    const s = buildStoreSsrSummary(baseSnapshot({ peakTimeLabel: "--:--", peakTotal: 0 }));
    expect(s!.peakText).toBeNull();
  });

  it("人数が 0 のときは人数・比率を出さない", () => {
    const s = buildStoreSsrSummary(
      baseSnapshot({ nowMen: 0, nowWomen: 0, nowTotal: 0, series: [] }),
    );
    // ピークだけは実データとして残る
    expect(s!.occupancyValue).toBeNull();
    expect(s!.genderStats).toEqual([]);
    expect(s!.ratioText).toBeNull();
    expect(s!.peakText).toBe("22:15（男性30名 / 女性28名）");
  });

  it("最終実測 ts が不正なら最終更新を出さない", () => {
    expect(buildStoreSsrSummary(baseSnapshot({ latestActualTs: null }))!.updatedText).toBeNull();
    expect(buildStoreSsrSummary(baseSnapshot({ latestActualTs: "not-a-date" }))!.updatedText).toBeNull();
  });

  it("実データが一つも取れなければ null", () => {
    const s = buildStoreSsrSummary(
      baseSnapshot({
        nowMen: 0,
        nowWomen: 0,
        nowTotal: 0,
        peakTimeLabel: "--:--",
        peakTotal: 0,
        series: [],
        latestActualTs: null,
      }),
    );
    expect(s).toBeNull();
  });
});

describe("rollUpHourlyActuals", () => {
  it("実測点だけを時間帯ごとにまとめ、夜の流れ順（19時→翌04時）に並べる", () => {
    const series: TimeSeriesPoint[] = [
      pt("23:00", 30, 30),
      pt("23:30", 35, 35),
      pt("01:00", 20, 20),
      pt("19:00", 10, 10),
      { label: "02:00", menActual: null, womenActual: null, menForecast: 50, womenForecast: 50 },
    ];
    expect(rollUpHourlyActuals(series)).toEqual([
      { hour: "19", total: 20 },
      { hour: "23", total: 70 }, // 同じ時間帯は最大値
      { hour: "01", total: 40 },
    ]);
  });

  it("予測しか無い点は無視する（予測を実測として出さない）", () => {
    const series: TimeSeriesPoint[] = [
      { label: "21:00", menActual: null, womenActual: null, menForecast: 40, womenForecast: 40 },
    ];
    expect(rollUpHourlyActuals(series)).toEqual([]);
  });

  it("時間帯が1つしか無ければサマリーを出さない", () => {
    const s = buildStoreSsrSummary(baseSnapshot({ series: [pt("19:00", 10, 12)] }));
    expect(s!.hourly).toEqual([]);
  });

  it("オリエンタルは人数、相席屋は % で時間帯別を出す", () => {
    const series = [pt("19:00", 10, 12), pt("20:00", 15, 18)];
    expect(buildStoreSsrSummary(baseSnapshot({ series }))!.hourly).toEqual([
      { label: "19時", value: "22人" },
      { label: "20時", value: "33人" },
    ]);
    const ay = buildStoreSsrSummary(
      baseSnapshot({ brand: "aisekiya", capacity: 50, series }),
    );
    expect(ay!.hourly).toEqual([
      { label: "19時", value: "約22%" },
      { label: "20時", value: "約33%" },
    ]);
  });
});
