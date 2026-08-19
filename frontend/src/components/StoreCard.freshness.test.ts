import { describe, expect, it } from "vitest";

import { staleFreshnessLabel } from "./StoreCard";
import { REALTIME_STALE_THRESHOLD_MIN } from "@/lib/forecast/seriesAnalysis";

/**
 * 所見4: 一覧/マイページ/関連店舗の StoreCard が最新行の人数を鮮度なしで「いま」として表示し、
 * 昼間に閉店直前の残留人数がそのまま出ていた。StoreRealtimeStatusCard.tsx と同じ
 * computeFreshness / しきい値・文言（「閉店中・最終 HH:MM 時点」）を使って stale を検知することを確認する。
 */
describe("staleFreshnessLabel", () => {
  const T0 = new Date("2026-08-19T12:00:00+09:00");

  it("stats が無ければ ts があってもラベルを出さない（数値が無いのにラベルだけ出る誤表示を防ぐ）", () => {
    expect(staleFreshnessLabel("2026-08-19T00:00:00+09:00", false, T0)).toBeNull();
  });

  it("ts が無ければラベルを出さない（従来どおり数値のみ表示）", () => {
    expect(staleFreshnessLabel(null, true, T0)).toBeNull();
    expect(staleFreshnessLabel(undefined, true, T0)).toBeNull();
  });

  it(`しきい値未満（${REALTIME_STALE_THRESHOLD_MIN}分未満）は fresh のためラベルを出さない`, () => {
    const fresh = new Date(T0.getTime() - (REALTIME_STALE_THRESHOLD_MIN - 1) * 60_000).toISOString();
    expect(staleFreshnessLabel(fresh, true, T0)).toBeNull();
  });

  it(`しきい値以上（${REALTIME_STALE_THRESHOLD_MIN}分以上）は「閉店中・最終 HH:MM 時点」を出す`, () => {
    const stale = new Date(T0.getTime() - REALTIME_STALE_THRESHOLD_MIN * 60_000).toISOString();
    const label = staleFreshnessLabel(stale, true, T0);
    expect(label).toMatch(/^閉店中・最終 \d{2}:\d{2} 時点$/);
  });

  it("昼間に閉店直前(04:55)の残留データが残っているケースを再現する", () => {
    // 12:00 時点で最新実測が当日04:55 → 7時間以上前 → 必ず stale
    const closedAt0455 = "2026-08-19T04:55:00+09:00";
    const label = staleFreshnessLabel(closedAt0455, true, T0);
    expect(label).toContain("閉店中・最終 04:55 時点");
  });
});
