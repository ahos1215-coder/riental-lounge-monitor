// frontend/src/lib/date/jst.test.ts
//
// JST 日付ヘルパー一本化（C-01 / D-04）の番犬テスト。
//
// ねらい: lib/date/jst.ts へ集約する前と後で「出力文字列が1文字も変わらない」ことを
// 機械的に固定する。各 describe の先頭に集約前の実装をそのままコピーして持ち、
// 境界時刻の表に対して「旧実装 === 現在の公開関数 / 新ヘルパー」を突き合わせる。
// このファイルは集約前の時点で緑であり、集約後も緑のままでなければならない。
import { describe, expect, it } from "vitest";

import {
  JST_TIME_ZONE,
  NIGHT_SESSION_SHIFT_HOURS,
  jstDateParts,
  jstHm,
  jstYmd,
  nightSessionAnchorUtcMs,
} from "./jst";
import { formatNowHmJst } from "./nightWindow";
import { jstNightSessionDate } from "@/lib/dateFormat";
import { detectAisekiyaDayTypeJst, detectDayTypeJst } from "@/lib/pricing/jpHolidays";
import { nightWindowIso } from "@/lib/blog/insightFromRange";
import { buildSeries } from "@/lib/forecast/seriesAnalysis";

/**
 * 境界時刻の表。JST 0:00 / 5:59 / 6:00（夜セッションの -6h 境界）、18:59 / 19:00
 * （表示夜窓の境界）、23:59、月またぎ、年またぎ、UTC 表記入力、閏日を含む。
 */
const BOUNDARY_ISO = [
  "2026-08-19T00:00:00+09:00",
  "2026-08-19T05:59:00+09:00",
  "2026-08-19T05:59:59+09:00",
  "2026-08-19T06:00:00+09:00",
  "2026-08-19T12:00:00+09:00",
  "2026-08-19T18:59:00+09:00",
  "2026-08-19T19:00:00+09:00",
  "2026-08-19T23:59:00+09:00",
  // 月またぎ
  "2026-09-01T00:00:00+09:00",
  "2026-09-01T02:00:00+09:00",
  "2026-08-31T23:59:00+09:00",
  // 年またぎ
  "2027-01-01T01:00:00+09:00",
  "2026-12-31T23:59:00+09:00",
  // 閏日
  "2028-02-29T03:00:00+09:00",
  "2028-03-01T05:00:00+09:00",
  // UTC 表記の入力（JST へ変換されること）
  "2026-08-19T21:00:00Z",
  "2026-08-19T20:00:00Z",
  "2026-08-19T15:00:00Z",
  "2026-12-31T15:00:00Z",
] as const;

const BOUNDARY_DATES = BOUNDARY_ISO.map((iso) => new Date(iso));

// ---------------------------------------------------------------------------
// 集約前の実装（コピー）
// ---------------------------------------------------------------------------

/** 旧 nightWindow.jstDateParts / 旧 jpHolidays.jstParts（両者バイト一致） */
function oldJstParts(d: Date): { year: number; month: number; day: number; hour: number } {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Tokyo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    hourCycle: "h23",
  }).formatToParts(d);
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "0";
  return {
    year: Number(get("year")),
    month: Number(get("month")),
    day: Number(get("day")),
    hour: Number(get("hour")),
  };
}

/** 旧 insightFromRange.fmtYmdTokyo / 旧 parseLineIntent.todayYmdTokyo / 旧 blog-draft.todayYmdJst */
function oldYmdTokyo(d: Date): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Tokyo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(d);
}

/** 旧 nightWindow.formatNowHmJst / 旧 insightFromRange.fmtHmTokyo */
function oldHmTokyo(d: Date): string {
  return new Intl.DateTimeFormat("ja-JP", {
    timeZone: "Asia/Tokyo",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(d);
}

/** 旧 seriesAnalysis.formatLabel（toLocaleTimeString 版・hour12 未指定） */
function oldFormatLabel(ts: string): string {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  return d.toLocaleTimeString("ja-JP", { timeZone: "Asia/Tokyo", hour: "2-digit", minute: "2-digit" });
}

const DAY_MS = 24 * 60 * 60 * 1000;

/** 旧 jpHolidays の夜アンカー算出（detectDayTypeJst / detectAisekiyaDayTypeJst で8行コピーだった部分） */
function oldAnchorMs(now: Date): number {
  const p = oldJstParts(now);
  let anchorMs = Date.UTC(p.year, p.month - 1, p.day);
  if (p.hour < 6) {
    anchorMs -= DAY_MS;
  }
  return anchorMs;
}

/** 旧 dateFormat.jstNightSessionDate（-6h 規約の YYYY-MM-DD 化） */
function oldNightSessionDate(now: Date): string {
  if (Number.isNaN(now.getTime())) return "";
  try {
    const parts = new Intl.DateTimeFormat("en-CA", {
      timeZone: "Asia/Tokyo",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      hourCycle: "h23",
    }).formatToParts(now);
    const get = (type: string) => Number(parts.find((p) => p.type === type)?.value ?? NaN);
    const year = get("year");
    const month = get("month");
    const day = get("day");
    const hour = get("hour");
    if ([year, month, day, hour].some((v) => !Number.isFinite(v))) return "";
    const base = Date.UTC(year, month - 1, day);
    const shifted = new Date(hour < 6 ? base - 86_400_000 : base);
    const pad = (n: number) => String(n).padStart(2, "0");
    return `${shifted.getUTCFullYear()}-${pad(shifted.getUTCMonth() + 1)}-${pad(shifted.getUTCDate())}`;
  } catch {
    return "";
  }
}

// ---------------------------------------------------------------------------

describe("lib/date/jst の定数", () => {
  it("タイムゾーンと夜セッションのシフト時間が Python 側規約(-6h)と一致する", () => {
    expect(JST_TIME_ZONE).toBe("Asia/Tokyo");
    expect(NIGHT_SESSION_SHIFT_HOURS).toBe(6);
  });
});

describe("jstDateParts は旧 jstDateParts / jstParts と同じ値を返す", () => {
  for (const iso of BOUNDARY_ISO) {
    it(`${iso}`, () => {
      expect(jstDateParts(new Date(iso))).toEqual(oldJstParts(new Date(iso)));
    });
  }
});

describe("jstYmd は旧 fmtYmdTokyo / todayYmdTokyo / todayYmdJst と1文字も違わない", () => {
  for (const iso of BOUNDARY_ISO) {
    it(`${iso}`, () => {
      const d = new Date(iso);
      expect(jstYmd(d)).toBe(oldYmdTokyo(d));
      expect(jstYmd(d)).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    });
  }

  it("引数省略時は現在時刻の JST 日付", () => {
    expect(jstYmd()).toBe(oldYmdTokyo(new Date()));
  });
});

describe("jstHm は旧 formatNowHmJst / fmtHmTokyo / formatLabel と1文字も違わない", () => {
  for (const iso of BOUNDARY_ISO) {
    it(`${iso}`, () => {
      const d = new Date(iso);
      expect(jstHm(d)).toBe(oldHmTokyo(d));
      // seriesAnalysis.formatLabel（toLocaleTimeString 版）とも出力一致すること。
      // ここが崩れたら formatLabel の差し替えは行ってはいけない。
      expect(jstHm(d)).toBe(oldFormatLabel(iso));
      expect(jstHm(d)).toMatch(/^\d{2}:\d{2}$/);
    });
  }

  it("公開関数 formatNowHmJst（import 互換のため名前を維持）も同じ出力", () => {
    for (const d of BOUNDARY_DATES) {
      expect(formatNowHmJst(d)).toBe(oldHmTokyo(d));
    }
  });
});

describe("nightSessionAnchorUtcMs は旧 jpHolidays のアンカー算出と一致する", () => {
  for (const iso of BOUNDARY_ISO) {
    it(`${iso}`, () => {
      expect(nightSessionAnchorUtcMs(new Date(iso))).toBe(oldAnchorMs(new Date(iso)));
    });
  }
});

describe("jstNightSessionDate（公開関数）は集約前の実装と同じ文字列を返す", () => {
  for (const iso of BOUNDARY_ISO) {
    it(`${iso}`, () => {
      expect(jstNightSessionDate(new Date(iso))).toBe(oldNightSessionDate(new Date(iso)));
    });
  }

  it("不正な Date は空文字（判定不能フォールバック）", () => {
    expect(jstNightSessionDate(new Date("not-a-date"))).toBe("");
    expect(oldNightSessionDate(new Date("not-a-date"))).toBe("");
  });
});

describe("detectDayTypeJst / detectAisekiyaDayTypeJst の anchorYmd は集約前と一致する", () => {
  const pad = (n: number) => String(n).padStart(2, "0");
  const utcYmd = (ms: number) => {
    const d = new Date(ms);
    return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`;
  };

  for (const iso of BOUNDARY_ISO) {
    it(`${iso}`, () => {
      const d = new Date(iso);
      const expected = utcYmd(oldAnchorMs(d));
      expect(detectDayTypeJst(d).anchorYmd).toBe(expected);
      expect(detectAisekiyaDayTypeJst(d).anchorYmd).toBe(expected);
    });
  }
});

describe("nightWindowIso（insightFromRange の日付演算）は月またぎ・年またぎで不変", () => {
  it("通常日", () => {
    expect(nightWindowIso("2026-08-19")).toEqual({
      from: "2026-08-19T19:00:00+09:00",
      to: "2026-08-20T05:00:00+09:00",
      label: "Tonight",
    });
  });

  it("月またぎ", () => {
    expect(nightWindowIso("2026-08-31").to).toBe("2026-09-01T05:00:00+09:00");
  });

  it("年またぎ", () => {
    expect(nightWindowIso("2026-12-31").to).toBe("2027-01-01T05:00:00+09:00");
  });

  it("閏日", () => {
    expect(nightWindowIso("2028-02-29").to).toBe("2028-03-01T05:00:00+09:00");
  });
});

describe("buildSeries の label は HH:MM 2桁ゼロ埋めのまま（ssrSummary の /^(\\d{2}):\\d{2}$/ 依存）", () => {
  it("実測の label が旧 formatLabel と完全一致する", () => {
    const actuals = BOUNDARY_ISO.map((iso) => ({ ts: iso, men: 5, women: 5, total: 10 }));
    const series = buildSeries(actuals, []);
    // buildSeries は ts の絶対時刻順に並べ替えて返すので、期待値も同じ順に並べる。
    const expected = [...BOUNDARY_ISO]
      .sort((a, b) => new Date(a).getTime() - new Date(b).getTime())
      .map((iso) => oldFormatLabel(iso));
    expect(series.map((p) => p.label)).toEqual(expected);
    for (const p of series) {
      expect(p.label).toMatch(/^\d{2}:\d{2}$/);
    }
  });
});
