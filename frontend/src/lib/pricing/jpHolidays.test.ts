import { describe, expect, it } from "vitest";

import { detectDayTypeJst, isJpHoliday } from "./jpHolidays";

describe("isJpHoliday", () => {
  it("knows 2026 holidays", () => {
    expect(isJpHoliday("2026-01-01")).toBe(true);
    expect(isJpHoliday("2026-02-11")).toBe(true);
    expect(isJpHoliday("2026-09-22")).toBe(true); // 国民の休日
  });

  it("returns false for plain days", () => {
    expect(isJpHoliday("2026-07-07")).toBe(false);
    expect(isJpHoliday("2026-04-01")).toBe(false);
  });
});

describe("detectDayTypeJst", () => {
  it("Friday evening is weekend (金曜)", () => {
    // 2026-07-10 は金曜
    const d = detectDayTypeJst(new Date("2026-07-10T21:00:00+09:00"));
    expect(d.dayType).toBe("weekend");
    expect(d.reason).toBe("金曜");
    expect(d.dowLabel).toBe("金");
  });

  it("Saturday evening is weekend (土曜)", () => {
    // 2026-07-11 は土曜
    const d = detectDayTypeJst(new Date("2026-07-11T21:00:00+09:00"));
    expect(d.dayType).toBe("weekend");
    expect(d.reason).toBe("土曜");
  });

  it("holiday-eve is weekend (祝前日)", () => {
    // 2026-02-10(火) の翌日 2/11 は建国記念の日
    const d = detectDayTypeJst(new Date("2026-02-10T21:00:00+09:00"));
    expect(d.dayType).toBe("weekend");
    expect(d.reason).toBe("祝前日");
    expect(d.dowLabel).toBe("火");
  });

  it("plain Tuesday is weekday", () => {
    // 2026-07-07(火)、翌日は祝日ではない
    const d = detectDayTypeJst(new Date("2026-07-07T21:00:00+09:00"));
    expect(d.dayType).toBe("weekday");
    expect(d.reason).toBe("平日");
    expect(d.dowLabel).toBe("火");
  });

  it("Saturday 2am counts as Friday night (weekend, 金曜)", () => {
    // 土曜の午前2時 = 金曜の夜営業の続き
    const d = detectDayTypeJst(new Date("2026-07-11T02:00:00+09:00"));
    expect(d.dayType).toBe("weekend");
    expect(d.reason).toBe("金曜");
    expect(d.anchorYmd).toBe("2026-07-10");
  });

  it("Monday 2am counts as Sunday night (weekday)", () => {
    // 月曜の午前2時 = 日曜の夜営業の続き（日曜は平日料金）
    const d = detectDayTypeJst(new Date("2026-07-13T02:00:00+09:00"));
    expect(d.dayType).toBe("weekday");
    expect(d.anchorYmd).toBe("2026-07-12");
  });

  it("Sunday evening is weekday", () => {
    const d = detectDayTypeJst(new Date("2026-07-12T21:00:00+09:00"));
    expect(d.dayType).toBe("weekday");
  });
});
