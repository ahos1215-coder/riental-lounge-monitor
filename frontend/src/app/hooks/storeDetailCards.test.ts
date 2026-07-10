import { describe, it, expect } from "vitest";
import {
  computeFreshness,
  isPeakPassed,
  peakProgressChip,
  pickPeak,
  REALTIME_STALE_THRESHOLD_MIN,
  type StoreSnapshot,
  type TimeSeriesPoint,
} from "./storePreviewSnapshot";

/**
 * 店舗詳細ページの2つのロジックバグ修正の回帰テスト。
 *
 * #1「ピークまで あと約◯人/%」チップがピーク通過後も"これから盛り上がる"方向へ誤誘導する問題:
 *    peakProgressChip / isPeakPassed が「ピーク時刻 < 現在時刻」で正しく分岐すること。
 * #8「リアルタイム」人数に鮮度表示が無い問題:
 *    computeFreshness が latestActualTs から「◯分前更新」/「最終 HH:MM 時点」/非表示を出すこと。
 */

const NOW = new Date("2026-07-10T13:00:00Z"); // 22:00 JST
const FUTURE = "2026-07-10T14:00:00Z"; // NOW+1h
const PAST = "2026-07-10T12:00:00Z"; // NOW-1h（JST 21:00）

// peakProgressChip が必要とする最小フィールドだけを持つスナップショット断片を作る。
function snap(partial: Partial<StoreSnapshot>): Pick<
  StoreSnapshot,
  "brand" | "capacity" | "peakTotal" | "nowTotal" | "peakTs" | "completedNight" | "recommendation"
> {
  return {
    brand: "oriental",
    capacity: null,
    peakTotal: 0,
    nowTotal: 0,
    peakTs: null,
    completedNight: false,
    recommendation: "データ取得済み",
    ...partial,
  };
}

describe("isPeakPassed", () => {
  it("returns false when the peak time is in the future (more people still coming)", () => {
    expect(isPeakPassed(FUTURE, NOW)).toBe(false);
  });

  it("returns true when the peak time is in the past (crowd is declining)", () => {
    expect(isPeakPassed(PAST, NOW)).toBe(true);
  });

  it("returns false for null / undefined / invalid timestamps (unknown = safe default)", () => {
    expect(isPeakPassed(null, NOW)).toBe(false);
    expect(isPeakPassed(undefined, NOW)).toBe(false);
    expect(isPeakPassed("not-a-date", NOW)).toBe(false);
  });
});

describe("peakProgressChip — #1 peak-past misdirection fix", () => {
  it("in-progress night, peak in FUTURE (人数) → shows 'ピークまで あと約◯人'", () => {
    const chip = peakProgressChip(
      snap({ brand: "oriental", peakTotal: 100, nowTotal: 60, peakTs: FUTURE }),
      NOW,
    );
    expect(chip).toBe("ピークまで あと約40人");
  });

  it("in-progress night, peak in FUTURE (相席屋 %モード) → shows 'ピークまで あと約◯%'", () => {
    const chip = peakProgressChip(
      snap({ brand: "aisekiya", capacity: 50, peakTotal: 60, nowTotal: 20, peakTs: FUTURE }),
      NOW,
    );
    // peakPct = 60/(50*2)=60%, nowPct = 20/100=20%, delta=40%
    expect(chip).toBe("ピークまで あと約40%");
  });

  it("in-progress night, peak already PASSED → replaced with truthful 'ピークは過ぎました' (no more 'あと約')", () => {
    const chip = peakProgressChip(
      // total < peak なので旧ロジックなら「あと約40人」を出し続けていた
      snap({ brand: "oriental", peakTotal: 100, nowTotal: 60, peakTs: PAST }),
      NOW,
    );
    expect(chip).toBe("ピークは過ぎました（落ち着き傾向）");
    expect(chip).not.toContain("あと約");
  });

  it("completed night (retrospective) → NEVER shows 'あと約' nor 'ピークは過ぎました' (falls back to recommendation)", () => {
    const chip = peakProgressChip(
      snap({
        brand: "oriental",
        peakTotal: 100,
        nowTotal: 60,
        peakTs: PAST,
        completedNight: true,
        recommendation: "◎",
      }),
      NOW,
    );
    expect(chip).toBe("おすすめ度 ◎");
    expect(chip).not.toContain("あと約");
    expect(chip).not.toContain("ピークは過ぎました");
  });

  it("completed night with no real recommendation → returns null (chip omitted)", () => {
    const chip = peakProgressChip(
      snap({ peakTotal: 100, nowTotal: 60, peakTs: PAST, completedNight: true, recommendation: "データなし" }),
      NOW,
    );
    expect(chip).toBeNull();
  });

  it("in-progress, peakTs null but delta>0 → keeps legacy 'あと約' (unknown peak time = safe default)", () => {
    const chip = peakProgressChip(
      snap({ brand: "oriental", peakTotal: 100, nowTotal: 60, peakTs: null }),
      NOW,
    );
    expect(chip).toBe("ピークまで あと約40人");
  });

  it("in-progress, peak reached (delta 0) with recommendation → falls back to おすすめ度", () => {
    const chip = peakProgressChip(
      snap({ brand: "oriental", peakTotal: 60, nowTotal: 60, peakTs: FUTURE, recommendation: "○" }),
      NOW,
    );
    expect(chip).toBe("おすすめ度 ○");
  });
});

describe("pickPeak — carries the peak point's ts", () => {
  it("returns peakTs of the most crowded series point", () => {
    const series: TimeSeriesPoint[] = [
      { ts: "2026-07-10T10:00:00Z", label: "19:00", menActual: 5, womenActual: 5, menForecast: null, womenForecast: null },
      { ts: "2026-07-10T12:30:00Z", label: "21:30", menActual: 40, womenActual: 40, menForecast: null, womenForecast: null },
      { ts: "2026-07-10T14:00:00Z", label: "23:00", menActual: 10, womenActual: 10, menForecast: null, womenForecast: null },
    ];
    const peak = pickPeak(series);
    expect(peak.peakTs).toBe("2026-07-10T12:30:00Z");
    expect(peak.peakTimeLabel).toBe("21:30");
    expect(peak.peakTotal).toBe(80);
  });

  it("returns peakTs null when the series has no data", () => {
    expect(pickPeak([]).peakTs).toBeNull();
  });
});

describe("computeFreshness — #8 realtime freshness display", () => {
  it("fresh: data 5 minutes old → '5分前更新'", () => {
    const ts = new Date(NOW.getTime() - 5 * 60_000).toISOString();
    const info = computeFreshness(ts, NOW);
    expect(info.state).toBe("fresh");
    if (info.state === "fresh") {
      expect(info.minutesAgo).toBe(5);
      expect(info.label).toBe("5分前更新");
    }
  });

  it("fresh: data 0 minutes old → 'たった今更新' (never a misleading raw '0分前')", () => {
    const info = computeFreshness(NOW.toISOString(), NOW);
    expect(info.state).toBe("fresh");
    if (info.state === "fresh") {
      expect(info.label).toBe("たった今更新");
    }
  });

  it("stale: data older than the threshold → '最終 HH:MM 時点' note (JST), not a live number", () => {
    const ts = new Date(NOW.getTime() - 25 * 60_000).toISOString(); // 25min ago, JST 21:35
    const info = computeFreshness(ts, NOW);
    expect(info.state).toBe("stale");
    if (info.state === "stale") {
      expect(info.minutesAgo).toBe(25);
      expect(info.label).toBe("最終 21:35 時点");
      expect(info.asOfLabel).toBe("21:35");
    }
  });

  it("exactly at the threshold counts as stale", () => {
    const ts = new Date(NOW.getTime() - REALTIME_STALE_THRESHOLD_MIN * 60_000).toISOString();
    expect(computeFreshness(ts, NOW).state).toBe("stale");
  });

  it("null / invalid latestActualTs → 'none' (no freshness indicator at all)", () => {
    expect(computeFreshness(null, NOW).state).toBe("none");
    expect(computeFreshness(undefined, NOW).state).toBe("none");
    expect(computeFreshness("not-a-date", NOW).state).toBe("none");
  });

  it("future timestamp (device clock skew) is clamped to 0 minutes, not negative", () => {
    const ts = new Date(NOW.getTime() + 3 * 60_000).toISOString();
    const info = computeFreshness(ts, NOW);
    expect(info.state).toBe("fresh");
    if (info.state === "fresh") {
      expect(info.minutesAgo).toBe(0);
      expect(info.label).toBe("たった今更新");
    }
  });
});
