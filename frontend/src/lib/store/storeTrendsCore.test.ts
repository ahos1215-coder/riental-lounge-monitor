import { describe, expect, it } from "vitest";
import {
  buildStoreTrendEntry,
  mergeWeeklyHeatmaps,
  selectRecentWeekFiles,
} from "../../../scripts/lib/storeTrendsCore.mjs";

const cell = (day: number, hour: number, occ: number, fem: number, n: number) => ({
  day,
  hour,
  avg_occupancy: occ,
  avg_female_ratio: fem,
  sample_count: n,
});
const doc = (start: string, end: string, cells: ReturnType<typeof cell>[]) => ({
  period: { start, end },
  day_hour_heatmap: { cells },
});

describe("selectRecentWeekFiles", () => {
  it("新しい順に最大4週、不正名は無視", () => {
    const r = selectRecentWeekFiles([
      "2026-11-18.json",
      "2026-11-11.json",
      "2026-11-04.json",
      "2026-10-28.json",
      "2026-10-21.json",
      "index.json",
      "2026-11-11.bak",
    ]);
    expect(r).toEqual(["2026-11-18.json", "2026-11-11.json", "2026-11-04.json", "2026-10-28.json"]);
  });
  it("6日未満の再実行ファイルは採用しない", () => {
    const r = selectRecentWeekFiles(["2026-11-18.json", "2026-11-14.json", "2026-11-11.json"]);
    expect(r).toEqual(["2026-11-18.json", "2026-11-11.json"]);
  });
  it("ちょうど6日差は採用する", () => {
    expect(selectRecentWeekFiles(["2026-11-18.json", "2026-11-12.json"])).toHaveLength(2);
  });
  it("35日窓より古いものは採用しない", () => {
    const r = selectRecentWeekFiles(["2026-11-18.json", "2026-10-14.json", "2026-10-13.json"]);
    expect(r).toEqual(["2026-11-18.json", "2026-10-14.json"]);
  });
  it("空なら空", () => {
    expect(selectRecentWeekFiles([])).toEqual([]);
  });
});

describe("mergeWeeklyHeatmaps", () => {
  it("サンプル数で重み付き平均する", () => {
    const merged = mergeWeeklyHeatmaps([
      doc("", "", [cell(5, 23, 0.2, 0.4, 10)]),
      doc("", "", [cell(5, 23, 0.8, 0.6, 30)]),
    ]);
    expect(merged).toEqual([{ d: 5, h: 23, o: 0.65, f: 0.55, n: 40 }]);
  });
  it("サンプル0・非有限は除外し、曜日→時間帯順に並べる", () => {
    const merged = mergeWeeklyHeatmaps([
      doc("", "", [
        cell(5, 0, 0.5, 0.5, 12),
        cell(5, 23, 0.5, 0.5, 12),
        cell(0, 19, 0.5, 0.5, 0),
        cell(1, 19, Number.NaN, 0.5, 12),
        cell(1, 20, 0.1, 0.5, 12),
      ]),
    ]);
    expect(merged.map((c: { d: number; h: number }) => `${c.d}:${c.h}`)).toEqual(["1:20", "5:23", "5:0"]);
  });
});

describe("buildStoreTrendEntry", () => {
  it("期間の JST 日付と夜日付規約", () => {
    const e = buildStoreTrendEntry(
      ["2026-11-18.json", "2026-11-11.json"],
      [
        doc("2026-11-11T00:00:00+09:00", "2026-11-18T04:59:00+09:00", [cell(5, 23, 0.5, 0.5, 12)]),
        doc("2026-11-04T00:00:00+09:00", "2026-11-11T04:59:00+09:00", [cell(5, 23, 0.5, 0.5, 12)]),
      ],
    );
    expect(e).not.toBeNull();
    expect(e!.weeks).toEqual(["2026-11-18", "2026-11-11"]);
    expect(e!.periodStart).toBe("2026-11-04");
    expect(e!.periodEnd).toBe("2026-11-17");
  });
  it("UTC 表記でも JST で日付化する", () => {
    const e = buildStoreTrendEntry(
      ["2026-11-18.json"],
      [doc("2026-11-10T16:30:00+00:00", "2026-11-18T10:00:00+00:00", [cell(1, 20, 0.5, 0.5, 12)])],
    );
    expect(e!.periodStart).toBe("2026-11-11");
    expect(e!.periodEnd).toBe("2026-11-18");
  });
  it("docs 空・セル無しは null", () => {
    expect(buildStoreTrendEntry([], [])).toBeNull();
    expect(
      buildStoreTrendEntry(
        ["2026-11-18.json"],
        [doc("2026-11-11T00:00:00+09:00", "2026-11-18T00:00:00+09:00", [])],
      ),
    ).toBeNull();
  });
});
