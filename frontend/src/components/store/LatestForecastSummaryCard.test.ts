/**
 * F5（2026-08-21 外部レビュー）の番犬テスト。
 *
 * 旧挙動: LatestForecastSummaryCard は forecastStatus を一切見ずにチップを描画していた。
 * 予測が取れていない夜でも peakTotal は実測の最大値で埋まる（pickPeak は実測を優先する）ため、
 * 実測ピークが「予測ハイライト」として出て、同じ画面の
 * 「予測データを取得できませんでした」「今夜の予測が出たら表示されます」と矛盾していた。
 * さらに forecastUpdatedLabel の初期値 "--:--" が「予測更新 --:--」というチップになっていた。
 *
 * ここでは修正後の期待値を固定する（旧挙動はバグなので赤→実装→緑）。
 */
import { describe, expect, it } from "vitest";

import { buildHighlightSection } from "./LatestForecastSummaryCard";
import type { StoreSnapshot } from "@/lib/forecast/types";

const NOW = new Date("2026-08-21T12:00:00Z"); // JST 21:00

function snap(overrides: Partial<StoreSnapshot> = {}): StoreSnapshot {
  return {
    slug: "shibuya",
    name: "オリエンタルラウンジ 渋谷",
    area: "渋谷",
    brand: "oriental",
    capacity: null,
    level: "データ取得済み",
    nowTotal: 40,
    nowMen: 20,
    nowWomen: 20,
    peakTimeLabel: "22:00",
    peakTotal: 80,
    peakMen: 45,
    peakWomen: 35,
    recommendation: "データ取得済み",
    forecastUpdatedLabel: "更新済み",
    series: [],
    hasData: true,
    forecastStatus: "ok",
    latestActualTs: "2026-08-21T12:00:00Z",
    peakTs: "2026-08-21T13:00:00+09:00",
    completedNight: false,
    ...overrides,
  };
}

describe("buildHighlightSection（予測が無い夜に実測ピークを「予測」と名乗らせない）", () => {
  it("進行中の夜 + forecastStatus=ok なら従来どおり「予測ハイライト（要点）」を出す", () => {
    const section = buildHighlightSection(snap(), NOW);
    expect(section).not.toBeNull();
    expect(section?.heading).toBe("予測ハイライト（要点）");
    expect(section?.chips[0]).toContain("ピーク目安 22:00");
    expect(section?.chips.join(" / ")).toContain("予測更新 更新済み");
  });

  it.each(["unavailable", "retrying", "insufficient_history", "idle"] as const)(
    "進行中の夜で forecastStatus=%s なら、実測ピークがあってもセクションごと出さない",
    (forecastStatus) => {
      // 予測取得に失敗しても peakTotal / peakTimeLabel は実測の最大値のまま残る（F5 の本体）。
      expect(buildHighlightSection(snap({ forecastStatus }), NOW)).toBeNull();
    },
  );

  it("完了済みの夜は「実測ハイライト」と名乗り、予測の更新時刻チップは出さない", () => {
    const section = buildHighlightSection(
      snap({ completedNight: true, forecastStatus: "ok", forecastUpdatedLabel: "更新済み" }),
      NOW,
    );
    expect(section?.heading).toBe("この夜の実測ハイライト（要点）");
    expect(section?.chips.join(" / ")).not.toContain("予測更新");
    expect(section?.chips[0]).toContain("ピーク目安 22:00");
  });

  it("プレースホルダ（--:--, —, 空）は更新時刻・ピーク時刻として採用しない", () => {
    for (const placeholder of ["--:--", "—", "-", "", "  "]) {
      const section = buildHighlightSection(
        snap({ forecastUpdatedLabel: placeholder, peakTimeLabel: placeholder }),
        NOW,
      );
      // ピーク時刻もプレースホルダなので、残るのはピーク進捗チップだけ（もしくは null）。
      const joined = section?.chips.join(" / ") ?? "";
      expect(joined).not.toContain("--:--");
      expect(joined).not.toContain("予測更新");
      expect(joined).not.toContain("ピーク目安");
    }
  });

  it("チップが1つも作れないときは null（空の見出しだけを描かない）", () => {
    const section = buildHighlightSection(
      snap({
        peakTimeLabel: "--:--",
        peakTotal: 0,
        nowTotal: 0,
        peakTs: null,
        forecastUpdatedLabel: "--:--",
        recommendation: "データなし",
      }),
      NOW,
    );
    expect(section).toBeNull();
  });

  it("相席屋（%表示）の分岐は壊れていない — 人数ではなく席の埋まり具合(%)で出す", () => {
    const section = buildHighlightSection(
      snap({
        slug: "ay_chiba",
        brand: "aisekiya",
        capacity: 40,
        peakMen: 40,
        peakWomen: 40,
        peakTotal: 80,
      }),
      NOW,
    );
    expect(section?.chips[0]).toContain("%");
    expect(section?.chips[0]).not.toContain("名");
  });
});
