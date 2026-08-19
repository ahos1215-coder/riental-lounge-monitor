import { describe, expect, it } from "vitest";

import type { StoreMeta } from "@/app/config/stores";
import { computeNightBaseDate, computeNightWindowFromBaseDate } from "@/lib/date/nightWindow";
import { buildAreaLiveSummary, buildAreaStoreLiveLine } from "./areaLiveSummary";

const oriental = {
  slug: "nagasaki",
  storeId: "ol_nagasaki",
  label: "長崎",
  areaLabel: "長崎・浜んまち",
  regionLabel: "九州",
  mapsQueryBase: "長崎 浜町",
  brand: "oriental",
  capacity: null,
  lat: 32.74,
  lon: 129.87,
} as unknown as StoreMeta;

const aisekiya = {
  ...oriental,
  slug: "ay_ueno",
  storeId: "ay_ueno",
  label: "上野",
  brand: "aisekiya",
  capacity: 60,
} as unknown as StoreMeta;

// 2026-08-18 22:00 JST（進行中の夜）
const NOW = new Date("2026-08-18T13:00:00Z");
const window = computeNightWindowFromBaseDate(computeNightBaseDate(NOW));

const rows = [
  { ts: "2026-08-18T11:05:00Z", men: 8, women: 6, total: 14 }, // 20:05 JST
  { ts: "2026-08-18T12:10:00Z", men: 12, women: 9, total: 21 }, // 21:10
  { ts: "2026-08-18T12:55:00Z", men: 15, women: 10, total: 25 }, // 21:55
];

// 閉店まで（04:55 に 0 人で終わる、実際の一夜の形）
const fullNight = [
  { ts: "2026-08-18T10:30:00Z", men: 3, women: 2, total: 5 }, // 19:30
  { ts: "2026-08-18T13:15:00Z", men: 30, women: 28, total: 58 }, // 22:15 ← ピーク
  { ts: "2026-08-18T14:10:00Z", men: 25, women: 20, total: 45 }, // 23:10
  { ts: "2026-08-18T16:40:00Z", men: 12, women: 12, total: 24 }, // 01:40
  { ts: "2026-08-18T19:55:00Z", men: 0, women: 0, total: 0 }, // 04:55 閉店
];

describe("buildAreaStoreLiveLine（進行中の夜）", () => {
  it("オリエンタル: いま・ピーク・時間帯別・時点を出す", () => {
    const line = buildAreaStoreLiveLine(oriental, rows, window, false)!;
    expect(line.storeName).toBe("オリエンタルラウンジ 長崎");
    expect(line.nowText).toBe("男性15人 / 女性10人（男60% / 女40%）");
    expect(line.peakText).toBe("21:55 に最多（男性15人 / 女性10人（男60% / 女40%））");
    expect(line.hourlyText).toBe("20時 14人 / 21時 25人");
    expect(line.updatedText).toBe("21:55 時点");
  });

  it("相席屋: 人数を一切出さず%のみ（いま・ピーク・時間帯別すべて）", () => {
    const line = buildAreaStoreLiveLine(aisekiya, rows, window, false)!;
    const all = [line.nowText, line.peakText, line.hourlyText].join(" ");
    expect(all).not.toMatch(/\d+人/);
    expect(line.nowText).toMatch(/^席の埋まり具合 約\d+%（男性\d+% \/ 女性\d+%）$/);
    expect(line.hourlyText).toMatch(/^20時 約\d+% \/ 21時 約\d+%$/);
  });

  it("直近ティックが 0 人でも、その夜に人がいれば行は残る（いまだけ出さない）", () => {
    const line = buildAreaStoreLiveLine(oriental, fullNight, window, false)!;
    expect(line.nowText).toBeNull();
    expect(line.peakText).toBe("22:15 に最多（男性30人 / 女性28人（男52% / 女48%））");
    expect(line.hourlyText).toBe("19時 5人 / 22時 58人 / 23時 45人 / 1時 24人");
  });

  it("対象の夜の実測が無ければ null（昨夜の残骸を今夜として出さない）", () => {
    const stale = [{ ts: "2026-08-17T12:00:00Z", men: 9, women: 9, total: 18 }];
    expect(buildAreaStoreLiveLine(oriental, stale, window, false)).toBeNull();
  });

  it("その夜ずっと 0 人なら null（空箱を作らない）", () => {
    expect(
      buildAreaStoreLiveLine(
        oriental,
        [{ ts: "2026-08-18T12:00:00Z", men: 0, women: 0 }],
        window,
        false,
      ),
    ).toBeNull();
  });

  it("1時間分しか無ければ hourlyText は null", () => {
    const one = [{ ts: "2026-08-18T12:00:00Z", men: 3, women: 4, total: 7 }];
    const line = buildAreaStoreLiveLine(oriental, one, window, false)!;
    expect(line.hourlyText).toBeNull();
    expect(line.nowText).toBe("男性3人 / 女性4人（男43% / 女57%）");
  });
});

describe("buildAreaStoreLiveLine（完了した夜）", () => {
  it("「いま」は出さず、ピークと時間帯別と最終計測で語る", () => {
    const line = buildAreaStoreLiveLine(oriental, fullNight, window, true)!;
    expect(line.nowText).toBeNull();
    expect(line.peakText).toContain("22:15 に最多");
    expect(line.updatedText).toBe("最終計測 04:55");
    // 夜の順序（19→23→0→5）で並ぶ
    expect(line.hourlyText).toBe("19時 5人 / 22時 58人 / 23時 45人 / 1時 24人");
  });
});

describe("buildAreaLiveSummary", () => {
  it("進行中の夜は「今夜」・データのある店だけ並べる", () => {
    const s = buildAreaLiveSummary([oriental, aisekiya], { nagasaki: rows }, NOW)!;
    expect(s.nightLabel).toBe("今夜");
    expect(s.completed).toBe(false);
    expect(s.lines.map((l) => l.slug)).toEqual(["nagasaki"]);
  });

  it("昼間（05:00〜19:00）は「直近の営業夜（M/D）」ラベルで前夜の実測を使う", () => {
    const noon = new Date("2026-08-19T03:00:00Z"); // 12:00 JST 8/19 → 対象は 8/18 の夜
    const s = buildAreaLiveSummary([oriental], { nagasaki: fullNight }, noon)!;
    expect(s.nightLabel).toBe("直近の営業夜（8/18）");
    expect(s.completed).toBe(true);
    expect(s.lines).toHaveLength(1);
    expect(s.lines[0].nowText).toBeNull();
    expect(s.lines[0].peakText).toContain("22:15 に最多");
  });

  it("1店も出せなければ null", () => {
    expect(buildAreaLiveSummary([oriental], {}, NOW)).toBeNull();
  });
});
