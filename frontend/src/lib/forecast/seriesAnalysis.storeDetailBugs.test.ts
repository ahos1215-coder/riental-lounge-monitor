import { describe, it, expect } from "vitest";
import { computeFreshness, peakProgressChip, pickPeak } from "@/lib/forecast/seriesAnalysis";
import type { StoreSnapshot, TimeSeriesPoint } from "@/app/hooks/storePreviewSnapshot";

/**
 * 店舗詳細ページ 4 バグ修正のうち、純粋関数レイヤで検証できる 2 件の回帰テスト。
 *
 * rank2「完了夜のピークが予測点で上書き」: pickPeak(series, { actualOnly:true }) が
 *   実測点のみからピークを求め、実測ピークより高い予測点に化けないこと。
 * rank6「鮮度/ピーク文言が最大15分凍結」: now を進めると computeFreshness / peakProgressChip の
 *   出力が変わること（＝親の60秒ティックで now を差し替えれば文言が凍結せず進む）。
 */

// peakProgressChip が必要とする最小フィールドだけを持つスナップショット断片。
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

describe("pickPeak actualOnly — rank2 completed-night peak overwrite fix", () => {
  // 完了夜のオーバーレイ（overlayAllForecast=true）を再現した系列:
  // - 実測（秒粒度 ts）: ピーク 202（22:00）
  // - 予測のみ（15分グリッド ts、実測と別キー）: 220 が +35分後（22:35）に立つ
  const merged: TimeSeriesPoint[] = [
    { ts: "2026-07-10T12:45:12Z", label: "21:45", menActual: 90, womenActual: 95, menForecast: 88, womenForecast: 92 },
    { ts: "2026-07-10T13:00:07Z", label: "22:00", menActual: 100, womenActual: 102, menForecast: 96, womenForecast: 99 },
    { ts: "2026-07-10T13:15:03Z", label: "22:15", menActual: 80, womenActual: 85, menForecast: 82, womenForecast: 86 },
    { ts: "2026-07-10T13:35:00Z", label: "22:35", menActual: null, womenActual: null, menForecast: 110, womenForecast: 110 },
  ];

  it("default (in-progress) picks the higher forecast-only point (220 at 22:35) — intended for tonight's expected peak", () => {
    const peak = pickPeak(merged);
    expect(peak.peakTotal).toBe(220);
    expect(peak.peakTimeLabel).toBe("22:35");
    expect(peak.peakTs).toBe("2026-07-10T13:35:00Z");
  });

  it("actualOnly:true (completed night) picks the true ACTUAL peak (202 at 22:00), not the forecast 220", () => {
    const peak = pickPeak(merged, { actualOnly: true });
    expect(peak.peakTotal).toBe(202);
    expect(peak.peakTimeLabel).toBe("22:00");
    expect(peak.peakTs).toBe("2026-07-10T13:00:07Z");
    expect(peak.peakMen).toBe(100);
    expect(peak.peakWomen).toBe(102);
  });

  it("actualOnly:true ignores forecast-only points entirely (no forecast fallback)", () => {
    const forecastOnly: TimeSeriesPoint[] = [
      { ts: "2026-07-10T13:35:00Z", label: "22:35", menActual: null, womenActual: null, menForecast: 110, womenForecast: 110 },
    ];
    const peak = pickPeak(forecastOnly, { actualOnly: true });
    // 実測点が1つも無ければピークは 0（予測点で埋めない）。
    expect(peak.peakTotal).toBe(0);
    expect(peak.peakTs).toBeNull();
  });

  it("actualOnly:false (explicit) equals the default forecast-inclusive behavior", () => {
    expect(pickPeak(merged, { actualOnly: false })).toEqual(pickPeak(merged));
  });
});

describe("computeFreshness — rank6 time-only recompute unfreezes stale label", () => {
  const T0 = new Date("2026-07-10T13:00:00Z"); // JST 22:00
  const ts = T0.toISOString();

  it("advancing now (as the 60s tick does) moves the '◯分前更新' label without new data", () => {
    const at5 = computeFreshness(ts, new Date(T0.getTime() + 5 * 60_000));
    const at12 = computeFreshness(ts, new Date(T0.getTime() + 12 * 60_000));
    expect(at5.state).toBe("fresh");
    expect(at12.state).toBe("fresh");
    if (at5.state === "fresh") expect(at5.label).toBe("5分前更新");
    if (at12.state === "fresh") expect(at12.label).toBe("12分前更新");
  });

  it("same latestActualTs flips fresh → stale once enough time passes (not frozen at render time)", () => {
    const fresh = computeFreshness(ts, new Date(T0.getTime() + 10 * 60_000));
    const stale = computeFreshness(ts, new Date(T0.getTime() + 25 * 60_000));
    expect(fresh.state).toBe("fresh");
    expect(stale.state).toBe("stale");
  });
});

describe("peakProgressChip — rank6 time-only recompute flips 'あと約' → 'ピークは過ぎました'", () => {
  const peakTs = "2026-07-10T13:30:00Z"; // JST 22:30

  it("same snapshot: before the peak shows 'あと約', after the peak flips to 'ピークは過ぎました' as now advances", () => {
    const s = snap({ brand: "oriental", peakTotal: 100, nowTotal: 60, peakTs });
    const before = peakProgressChip(s, new Date("2026-07-10T13:00:00Z")); // 22:00 (peak未到達)
    const after = peakProgressChip(s, new Date("2026-07-10T14:00:00Z")); // 23:00 (peak通過)
    expect(before).toBe("ピークまで あと約40人");
    expect(after).toBe("ピークは過ぎました（落ち着き傾向）");
  });
});
