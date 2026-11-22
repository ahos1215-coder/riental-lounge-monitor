import { describe, expect, it } from "vitest";
import {
  buildStoreTrendSentences,
  formatTrendBasis,
  formatTrendPeriod,
  summarizeStoreTrend,
  type StoreTrendCell,
  type StoreTrendEntry,
} from "./storeTrends";

const NOW = new Date("2026-11-22T03:00:00Z");
const c = (d: number, h: number, o: number, f = 0.5, n = 48): StoreTrendCell => ({ d, h, o, f, n });
const entry = (cells: StoreTrendCell[], over: Partial<StoreTrendEntry> = {}): StoreTrendEntry => ({
  weeks: ["2026-11-18", "2026-11-11", "2026-11-04", "2026-10-28"],
  periodStart: "2026-10-22",
  periodEnd: "2026-11-17",
  cells,
  ...over,
});

describe("summarizeStoreTrend", () => {
  const base = [c(4, 22, 0.6), c(5, 23, 0.9), c(5, 2, 0.2), c(1, 22, 0.3)];
  it("MIN_WEEKS 未満は null", () => {
    expect(summarizeStoreTrend(entry(base, { weeks: ["2026-11-18"] }), { now: NOW })).toBeNull();
  });
  it("最新週が21日超で null、21日ちょうどは可", () => {
    const old = entry(base, { weeks: ["2026-10-31", "2026-10-25"] });
    expect(summarizeStoreTrend(old, { now: NOW })).toBeNull();
    expect(summarizeStoreTrend(old, { now: new Date("2026-11-21T14:59:00Z") })).not.toBeNull();
  });
  it("entry 無し・有効セル無しは null", () => {
    expect(summarizeStoreTrend(null, { now: NOW })).toBeNull();
    expect(summarizeStoreTrend(entry([c(5, 23, 0.9, 0.5, 11)]), { now: NOW })).toBeNull();
  });
  it("サンプル不足セルは除外される", () => {
    const s = summarizeStoreTrend(entry([...base, c(6, 23, 1, 0.5, 11)]), { now: NOW })!;
    expect(s.busiestDays).not.toContain(6);
  });
  it("同率は サンプル数多い→曜日小さい順", () => {
    const s = summarizeStoreTrend(
      entry([c(5, 23, 0.8, 0.5, 20), c(4, 22, 0.8, 0.5, 30), c(3, 21, 0.8, 0.5, 30), c(0, 20, 0.1)]),
      { now: NOW },
    )!;
    expect(s.busiestSlots.map((x) => `${x.d}:${x.h}`)).toEqual(["3:21", "4:22", "5:23"]);
  });
  it("quietestDay は3曜日以上かつ busiest と別のときのみ", () => {
    const two = summarizeStoreTrend(entry([c(4, 22, 0.9), c(1, 22, 0.1)]), { now: NOW })!;
    expect(two.quietestDay).toBeNull();
    const three = summarizeStoreTrend(entry([c(4, 22, 0.9), c(5, 22, 0.8), c(1, 22, 0.1)]), {
      now: NOW,
    })!;
    expect(three.quietestDay).toBe(1);
  });
});

describe("buildStoreTrendSentences", () => {
  it("通常ケース（性別あり）: 全文が固定テンプレートどおり", () => {
    const s = summarizeStoreTrend(
      entry([
        c(4, 19, 0.1, 0.4),
        c(4, 22, 0.8, 0.4),
        c(5, 19, 0.3, 0.4),
        c(5, 23, 1.0, 0.4),
        c(5, 0, 0.9, 0.4),
        c(1, 22, 0.3, 0.2),
        c(2, 22, 0.1, 0.2),
        c(6, 22, 0.4, 0.2),
      ]),
      { now: NOW },
    )!;
    expect(buildStoreTrendSentences(s, { showGenderRatio: true })).toEqual([
      "混みやすい曜日は土曜・金曜でした。",
      "特に混んだ時間帯は土曜23時台、土曜0時台、金曜22時台です。",
      "金・土の夜でも19時台は比較的空いていて、ピーク（23時台）の約2割の混み具合です。",
      "日〜木曜の夜の混み具合は、金・土の約4割です。",
      "比較的落ち着いているのは水曜の夜です。",
      "女性比率の平均は、金・土の夜が約40%、日〜木曜の夜が約20%でした。",
    ]);
  });
  it("1割未満・性別なし", () => {
    const s = summarizeStoreTrend(
      entry([c(5, 23, 1.0), c(5, 19, 0.04), c(4, 23, 1.0), c(1, 22, 0.02)]),
      { now: NOW },
    )!;
    const t = buildStoreTrendSentences(s, { showGenderRatio: false });
    expect(t).toContain("金・土の夜でも19時台は比較的空いていて、ピーク（23時台）の1割未満の混み具合です。");
    expect(t).toContain("日〜木曜の夜の混み具合は、金・土の1割未満です。");
    expect(t.some((x) => x.includes("女性比率"))).toBe(false);
  });
  it("空いている時間はピークより前からだけ選ぶ（閉店間際は選ばない）", () => {
    const s = summarizeStoreTrend(
      entry([c(5, 19, 0.5), c(5, 23, 1.0), c(5, 4, 0.05), c(1, 22, 0.3)]),
      { now: NOW },
    )!;
    expect(s.weekendQuietHour?.h).toBe(19);
    expect(buildStoreTrendSentences(s, { showGenderRatio: false })).toContain(
      "金・土の夜でも19時台は比較的空いていて、ピーク（23時台）の約5割の混み具合です。",
    );
    // ピークが開店直後の時間なら、それより前が無いので「空いている時間」の文は出さない
    const early = summarizeStoreTrend(entry([c(5, 19, 1.0), c(5, 23, 0.2), c(1, 22, 0.3)]), {
      now: NOW,
    })!;
    expect(early.weekendQuietHour).toBeNull();
    expect(
      buildStoreTrendSentences(early, { showGenderRatio: false }).some((x) => x.includes("比較的空いていて")),
    ).toBe(false);
  });
  it("同じくらい混む・曜日1つ", () => {
    const s = summarizeStoreTrend(entry([c(5, 23, 0.9), c(2, 23, 0.9)]), { now: NOW })!;
    expect(buildStoreTrendSentences(s, { showGenderRatio: true })).toContain(
      "日〜木曜の夜も、金・土と同じくらい混みます。",
    );
    const one = summarizeStoreTrend(entry([c(5, 23, 0.9)]), { now: NOW })!;
    expect(buildStoreTrendSentences(one, { showGenderRatio: true })[0]).toBe(
      "混みやすい曜日は土曜でした。",
    );
  });
  it("片側だけの女性比率", () => {
    const s = summarizeStoreTrend(entry([c(5, 23, 0.9, 0.35), c(4, 22, 0.5, 0.35)]), { now: NOW })!;
    expect(buildStoreTrendSentences(s, { showGenderRatio: true }).at(-1)).toBe(
      "金・土の夜の女性比率は平均約35%でした。",
    );
  });
});

describe("formatTrendBasis", () => {
  it("途切れの無い4週は「直近4週（期間）」", () => {
    expect(
      formatTrendBasis({ weeksUsed: 4, periodStart: "2026-10-21", periodEnd: "2026-11-17" }),
    ).toBe("直近4週（2026/10/21〜11/17）の実測から集計");
  });
  it("欠けた週があって期間が長いときは「期間のうちN週分」", () => {
    expect(
      formatTrendBasis({ weeksUsed: 4, periodStart: "2026-10-14", periodEnd: "2026-11-17" }),
    ).toBe("2026/10/14〜11/17のうち4週分の実測から集計");
  });
});

describe("formatTrendPeriod", () => {
  it("同年は終端の年を省略、年またぎは両方", () => {
    expect(formatTrendPeriod({ periodStart: "2026-10-22", periodEnd: "2026-11-17" })).toBe(
      "2026/10/22〜11/17",
    );
    expect(formatTrendPeriod({ periodStart: "2025-12-24", periodEnd: "2026-01-20" })).toBe(
      "2025/12/24〜2026/01/20",
    );
  });
});
