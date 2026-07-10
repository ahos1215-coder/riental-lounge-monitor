import { describe, expect, it } from "vitest";
import {
  buildActualSparklineFromRange,
  buildActualSparklineSeriesFromRange,
  buildGenderSparklineFromRange,
  buildGenderSparklineSeriesFromRange,
  segmentIndicesByTimeGaps,
  type StoreCardRangeRow,
} from "./storeCardRangeSparkline";

const MIN = 60_000;

/** 5分刻みで n 点、指定インデックスの直前に extraGapMinutes の穴を空けたタイムスタンプ列 */
function times5min(n: number, gapAt?: number, extraGapMinutes = 0): number[] {
  const base = Date.UTC(2026, 6, 9, 19, 55, 0);
  const out: number[] = [];
  let t = base;
  for (let i = 0; i < n; i++) {
    if (gapAt != null && i === gapAt) t += extraGapMinutes * MIN;
    out.push(t);
    t += 5 * MIN;
  }
  return out;
}

describe("segmentIndicesByTimeGaps", () => {
  it("閉店をまたぐ約14時間のギャップで2セグメントに分割する", () => {
    // 07-09 19:55(total=0) → 07-10 10:03(total=4) 相当の 848 分ギャップ
    const t0 = Date.UTC(2026, 6, 9, 19, 55, 0);
    const times = [
      t0,
      t0 + 5 * MIN,
      t0 + 10 * MIN,
      t0 + (10 + 848) * MIN, // 翌朝の最初の点
      t0 + (10 + 848 + 8) * MIN,
    ];
    const segments = segmentIndicesByTimeGaps(times);
    expect(segments).toEqual([
      [0, 1, 2],
      [3, 4],
    ]);
  });

  it("通常の5分間隔の系列は1セグメントのまま", () => {
    const times = times5min(12);
    const segments = segmentIndicesByTimeGaps(times);
    expect(segments).toHaveLength(1);
    expect(segments[0]).toHaveLength(12);
  });

  it("20分程度の軽微な穴では分割しない（60分の下限を超えない）", () => {
    const times = times5min(8, 4, 20);
    const segments = segmentIndicesByTimeGaps(times);
    expect(segments).toHaveLength(1);
  });

  it("空配列・単一点を安全に扱う", () => {
    expect(segmentIndicesByTimeGaps([])).toEqual([]);
    expect(segmentIndicesByTimeGaps([123])).toEqual([[0]]);
  });

  it("常に全インデックスを被覆する", () => {
    const times = times5min(6, 3, 900);
    const flat = segmentIndicesByTimeGaps(times).flat();
    expect(flat).toEqual([0, 1, 2, 3, 4, 5]);
  });

  it("NaN(ts欠損)の箇所では分割しない", () => {
    const t0 = Date.UTC(2026, 6, 9, 19, 55, 0);
    const times = [t0, NaN, t0 + 10 * MIN];
    const segments = segmentIndicesByTimeGaps(times);
    expect(segments).toHaveLength(1);
  });
});

describe("series builders carry aligned timestamps", () => {
  const rows: StoreCardRangeRow[] = [
    { ts: "2026-07-09T10:00:00Z", men: 2, women: 3 },
    { ts: "2026-07-09T10:05:00Z", men: 1, women: 4 },
    { ts: "2026-07-10T10:00:00Z", men: 0, women: 4 },
  ];

  it("buildActualSparklineSeriesFromRange は値と times が同数・同順", () => {
    const s = buildActualSparklineSeriesFromRange(rows, 12);
    expect(s.values).toEqual([5, 5, 4]);
    expect(s.times).toHaveLength(3);
    expect(s.times[0]).toBe(new Date("2026-07-09T10:00:00Z").getTime());
    // 後方互換: 従来 API は値のみを返す
    expect(buildActualSparklineFromRange(rows, 12)).toEqual(s.values);
  });

  it("buildGenderSparklineSeriesFromRange も men/women/times が揃う", () => {
    const s = buildGenderSparklineSeriesFromRange(rows, 12);
    expect(s.men).toEqual([2, 1, 0]);
    expect(s.women).toEqual([3, 4, 4]);
    expect(s.times).toHaveLength(3);
    const legacy = buildGenderSparklineFromRange(rows, 12);
    expect(legacy).toEqual({ men: s.men, women: s.women });
  });

  it("maxPoints で末尾を切っても値と times の対応が保たれる", () => {
    const s = buildActualSparklineSeriesFromRange(rows, 2);
    expect(s.values).toEqual([5, 4]);
    expect(s.times).toHaveLength(2);
    expect(s.times[0]).toBe(new Date("2026-07-09T10:05:00Z").getTime());
    expect(s.times[1]).toBe(new Date("2026-07-10T10:00:00Z").getTime());
  });

  it("十分な点数があれば末尾の閉店ギャップでセグメントが割れる", () => {
    // 5分刻みで一晩ぶん → 翌朝の1点、という現実に近い並び
    const t0 = Date.UTC(2026, 6, 9, 19, 0, 0);
    const gappedRows: StoreCardRangeRow[] = [];
    for (let i = 0; i < 6; i++) {
      gappedRows.push({ ts: new Date(t0 + i * 5 * MIN).toISOString(), total: i });
    }
    gappedRows.push({ ts: new Date(t0 + 6 * 5 * MIN + 840 * MIN).toISOString(), total: 4 });
    const s = buildActualSparklineSeriesFromRange(gappedRows, 12);
    const segments = segmentIndicesByTimeGaps(s.times);
    expect(segments).toHaveLength(2);
    expect(segments[1]).toEqual([6]);
  });
});
