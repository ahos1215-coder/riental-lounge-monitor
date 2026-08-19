import { describe, expect, it } from "vitest";

import { pickBusiestNight, type DailySummaryEntry } from "./WeeklySummary";

function night(
  date: string,
  peak: number,
  avg: number,
  day_label_ja = "月",
): DailySummaryEntry {
  return {
    date,
    day_label_ja,
    avg_occupancy: avg,
    peak_occupancy: peak,
    avg_female_ratio: 0.4,
    sample_count: 50,
  };
}

describe("pickBusiestNight（一番賑わった夜）", () => {
  it("ピークが最大の夜を選ぶ", () => {
    const picked = pickBusiestNight([
      night("2026-08-10", 0.6, 0.4),
      night("2026-08-11", 0.9, 0.3),
      night("2026-08-12", 0.7, 0.5),
    ]);
    expect(picked?.date).toBe("2026-08-11");
  });

  it("ピーク同値なら平均が高い夜を選ぶ（相席屋は 100% 頭打ちで同値が常態化する）", () => {
    const picked = pickBusiestNight([
      night("2026-08-10", 1.0, 0.42), // 先頭。従来はこれが常に選ばれていた
      night("2026-08-14", 1.0, 0.81), // 実際に一晩通して賑わった金曜
      night("2026-08-15", 1.0, 0.77),
    ]);
    expect(picked?.date).toBe("2026-08-14");
  });

  it("ピークも平均も同値なら先頭を維持する（選択が毎回ブレない）", () => {
    const picked = pickBusiestNight([
      night("2026-08-10", 1.0, 0.5),
      night("2026-08-11", 1.0, 0.5),
    ]);
    expect(picked?.date).toBe("2026-08-10");
  });

  it("ピークが高い夜は平均が低くても勝つ（タイブレークはあくまで同値時のみ）", () => {
    const picked = pickBusiestNight([
      night("2026-08-10", 0.95, 0.2),
      night("2026-08-11", 0.90, 0.9),
    ]);
    expect(picked?.date).toBe("2026-08-10");
  });

  it("空配列は null", () => {
    expect(pickBusiestNight([])).toBeNull();
  });
});
