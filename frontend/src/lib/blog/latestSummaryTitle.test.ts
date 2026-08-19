import { describe, expect, it } from "vitest";

import { buildLatestSummaryTitle } from "./latestSummaryTitle";
import { formatJstMonthDay, jstNightSessionDate } from "@/lib/dateFormat";

describe("jstNightSessionDate（夜セッション日付・-6h 規約）", () => {
  it("夜（21:30 JST）は当日", () => {
    expect(jstNightSessionDate(new Date("2026-08-19T21:30:00+09:00"))).toBe("2026-08-19");
  });

  it("深夜 03:00 JST は前夜扱い", () => {
    expect(jstNightSessionDate(new Date("2026-08-20T03:00:00+09:00"))).toBe("2026-08-19");
  });

  it("05:59 JST はまだ前夜、06:00 JST から当日に変わる", () => {
    expect(jstNightSessionDate(new Date("2026-08-20T05:59:00+09:00"))).toBe("2026-08-19");
    expect(jstNightSessionDate(new Date("2026-08-20T06:00:00+09:00"))).toBe("2026-08-20");
  });

  it("月またぎ・年またぎでも日付演算が壊れない", () => {
    expect(jstNightSessionDate(new Date("2026-09-01T02:00:00+09:00"))).toBe("2026-08-31");
    expect(jstNightSessionDate(new Date("2027-01-01T01:00:00+09:00"))).toBe("2026-12-31");
  });

  it("UTC 表記の入力でも JST に直して判定する", () => {
    // 2026-08-19 21:00 UTC = 2026-08-20 06:00 JST → 当日
    expect(jstNightSessionDate(new Date("2026-08-19T21:00:00Z"))).toBe("2026-08-20");
    // 2026-08-19 20:00 UTC = 2026-08-20 05:00 JST → 前夜
    expect(jstNightSessionDate(new Date("2026-08-19T20:00:00Z"))).toBe("2026-08-19");
  });

  it("不正な日付は空文字（呼び出し側でフォールバックできる）", () => {
    expect(jstNightSessionDate(new Date("not-a-date"))).toBe("");
  });
});

describe("formatJstMonthDay", () => {
  it("YYYY-MM-DD を M/D にする（ゼロ埋めしない）", () => {
    expect(formatJstMonthDay("2026-08-19")).toBe("8/19");
    expect(formatJstMonthDay("2026-01-05")).toBe("1/5");
  });

  it("形式が違えば空文字", () => {
    expect(formatJstMonthDay("2026/08/19")).toBe("");
    expect(formatJstMonthDay("")).toBe("");
    expect(formatJstMonthDay(undefined)).toBe("");
  });
});

describe("buildLatestSummaryTitle（デイリー要約カードの見出し）", () => {
  it("同じ夜のレポートなら「今日の傾向まとめ」", () => {
    // 21:30 生成 → 同日 23:00 に閲覧
    expect(buildLatestSummaryTitle("2026-08-19", new Date("2026-08-19T23:00:00+09:00"))).toBe(
      "今日の傾向まとめ",
    );
  });

  it("深夜 02:00 も同じ夜として「今日の傾向まとめ」のまま", () => {
    expect(buildLatestSummaryTitle("2026-08-19", new Date("2026-08-20T02:00:00+09:00"))).toBe(
      "今日の傾向まとめ",
    );
  });

  it("翌日の昼は「前回（M/D）の傾向まとめ」に変わる（前夜の記述を『今日』と偽らない）", () => {
    expect(buildLatestSummaryTitle("2026-08-19", new Date("2026-08-20T13:00:00+09:00"))).toBe(
      "前回（8/19）の傾向まとめ",
    );
  });

  it("06:00 JST を過ぎた朝から「前回」表示になる", () => {
    expect(buildLatestSummaryTitle("2026-08-19", new Date("2026-08-20T05:59:00+09:00"))).toBe(
      "今日の傾向まとめ",
    );
    expect(buildLatestSummaryTitle("2026-08-19", new Date("2026-08-20T06:00:00+09:00"))).toBe(
      "前回（8/19）の傾向まとめ",
    );
  });

  it("数日前のレポートでも日付付きで残す（カードごと消さない）", () => {
    expect(buildLatestSummaryTitle("2026-08-15", new Date("2026-08-19T20:00:00+09:00"))).toBe(
      "前回（8/15）の傾向まとめ",
    );
  });

  it("target_date が空・不正なら従来どおりの見出し（判定不能で「前回」と決めつけない）", () => {
    expect(buildLatestSummaryTitle("", new Date("2026-08-20T13:00:00+09:00"))).toBe(
      "今日の傾向まとめ",
    );
    expect(buildLatestSummaryTitle(null, new Date("2026-08-20T13:00:00+09:00"))).toBe(
      "今日の傾向まとめ",
    );
  });

  it("日付形式が想定外なら日付無しの「前回の傾向まとめ」", () => {
    expect(buildLatestSummaryTitle("20260819", new Date("2026-08-20T13:00:00+09:00"))).toBe(
      "前回の傾向まとめ",
    );
  });
});
