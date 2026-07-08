import { describe, expect, it } from "vitest";

import { detectAisekiyaDayTypeJst, detectDayTypeJst, isJpHoliday } from "./jpHolidays";

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

// ============================================================================
// 相席屋専用の曜日判定（金・土・日・祝日・祝前日=weekend/高料金）
// オリエンタル用 detectDayTypeJst との唯一の違いは日曜・祝日当日の扱い。
// ============================================================================

describe("detectAisekiyaDayTypeJst", () => {
  it("Sunday evening is weekend/high-rate for aisekiya (unlike oriental, which treats Sunday as weekday)", () => {
    // 2026-07-12 は日曜。同じ日時で detectDayTypeJst と結果が食い違うことを明示する。
    const aisekiya = detectAisekiyaDayTypeJst(new Date("2026-07-12T21:00:00+09:00"));
    const oriental = detectDayTypeJst(new Date("2026-07-12T21:00:00+09:00"));
    expect(aisekiya.dayType).toBe("weekend");
    expect(aisekiya.reason).toBe("日曜");
    expect(oriental.dayType).toBe("weekday");
  });

  it("a plain Tuesday is weekday for both brands", () => {
    // 2026-07-07(火)、翌日は祝日ではない
    const aisekiya = detectAisekiyaDayTypeJst(new Date("2026-07-07T21:00:00+09:00"));
    const oriental = detectDayTypeJst(new Date("2026-07-07T21:00:00+09:00"));
    expect(aisekiya.dayType).toBe("weekday");
    expect(aisekiya.reason).toBe("平日");
    expect(oriental.dayType).toBe("weekday");
  });

  it("Friday evening is weekend (same as oriental)", () => {
    const d = detectAisekiyaDayTypeJst(new Date("2026-07-10T21:00:00+09:00"));
    expect(d.dayType).toBe("weekend");
    expect(d.reason).toBe("金曜");
  });

  it("Saturday evening is weekend (same as oriental)", () => {
    const d = detectAisekiyaDayTypeJst(new Date("2026-07-11T21:00:00+09:00"));
    expect(d.dayType).toBe("weekend");
    expect(d.reason).toBe("土曜");
  });

  it("holiday-eve is weekend (same rule as oriental)", () => {
    // 2026-02-10(火) の翌日 2/11 は建国記念の日
    const d = detectAisekiyaDayTypeJst(new Date("2026-02-10T21:00:00+09:00"));
    expect(d.dayType).toBe("weekend");
    expect(d.reason).toBe("祝前日");
  });

  it("the holiday itself is weekend for aisekiya (oriental has no same-day-holiday rule)", () => {
    // 2026-02-11(水) は建国記念の日そのもの。オリエンタルは「祝前日」のみ判定するため
    // 祝日当日は平日料金になるが、相席屋は「祝日」自体も高料金対象。
    const aisekiya = detectAisekiyaDayTypeJst(new Date("2026-02-11T21:00:00+09:00"));
    const oriental = detectDayTypeJst(new Date("2026-02-11T21:00:00+09:00"));
    expect(aisekiya.dayType).toBe("weekend");
    expect(aisekiya.reason).toBe("祝日");
    expect(oriental.dayType).toBe("weekday");
  });

  it("Saturday 2am counts as Friday night (weekend, 金曜) — same anchor-date logic as oriental", () => {
    const d = detectAisekiyaDayTypeJst(new Date("2026-07-11T02:00:00+09:00"));
    expect(d.dayType).toBe("weekend");
    expect(d.reason).toBe("金曜");
    expect(d.anchorYmd).toBe("2026-07-10");
  });

  it("Monday 2am counts as Sunday night (weekend for aisekiya, since Sunday is high-rate)", () => {
    // 月曜の午前2時 = 日曜の夜営業の続き。相席屋は日曜が高料金のため weekend になる
    // （オリエンタルは同じ時刻でも weekday のまま＝ブランド差が正しく反映される）。
    const aisekiya = detectAisekiyaDayTypeJst(new Date("2026-07-13T02:00:00+09:00"));
    const oriental = detectDayTypeJst(new Date("2026-07-13T02:00:00+09:00"));
    expect(aisekiya.dayType).toBe("weekend");
    expect(aisekiya.reason).toBe("日曜");
    expect(aisekiya.anchorYmd).toBe("2026-07-12");
    expect(oriental.dayType).toBe("weekday");
  });
});
