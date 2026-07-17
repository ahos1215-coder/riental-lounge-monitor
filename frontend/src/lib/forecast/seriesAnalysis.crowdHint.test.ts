import { describe, expect, it } from "vitest";
import { crowdHintChip } from "./seriesAnalysis";
import type { StoreSnapshot } from "@/app/hooks/storePreviewSnapshot";

/**
 * rank3「過去夜タブで『ピーク比480%』の無意味表示」の回帰テスト。
 *
 * バグ: nowTotal は夜窓フィルタ前の「今まさにの人数」で計算されるため、
 * 昨日/先週/カスタム過去日タブ（completedNight=true）で見ても、選択中の過去夜の
 * peakTotal と組み合わせると無関係な比率になる
 * （本番実測: shibuya 199÷71=280%, ay_ueno 48÷10=480%）。
 * 修正: completedNight のときはチップ自体を出さない（null）。
 */
function snap(partial: Partial<StoreSnapshot>): Pick<
  StoreSnapshot,
  "completedNight" | "nowTotal" | "peakTotal"
> {
  return {
    completedNight: false,
    nowTotal: 0,
    peakTotal: 0,
    ...partial,
  };
}

describe("crowdHintChip — rank3 stale peak-ratio fix", () => {
  it("completed night (昨日/先週/カスタム過去日) → returns null, hiding the crowd/peak-ratio chip", () => {
    // 本番で確認された shibuya の再現値: 現在199人（今夜のライブ値）÷ 選択中の過去夜ピーク71人
    expect(crowdHintChip(snap({ completedNight: true, nowTotal: 199, peakTotal: 71 }))).toBeNull();
    // ay_ueno: 48÷10
    expect(crowdHintChip(snap({ completedNight: true, nowTotal: 48, peakTotal: 10 }))).toBeNull();
  });

  it("in-progress (live tonight) night → still returns the crowd hint + occupancy percent", () => {
    const info = crowdHintChip(snap({ completedNight: false, nowTotal: 60, peakTotal: 100 }));
    expect(info).toEqual({ crowd: "ほどよい目安", occupancyPercent: 60 });
  });

  it("in-progress, no peak yet (peakTotal 0) → occupancyPercent null, crowd falls back to '予測データ待ち'", () => {
    const info = crowdHintChip(snap({ completedNight: false, nowTotal: 0, peakTotal: 0 }));
    expect(info).toEqual({ crowd: "予測データ待ち", occupancyPercent: null });
  });

  it("in-progress, near peak (>=85%) → '混雑に近い目安'", () => {
    const info = crowdHintChip(snap({ completedNight: false, nowTotal: 90, peakTotal: 100 }));
    expect(info?.crowd).toBe("混雑に近い目安");
    expect(info?.occupancyPercent).toBe(90);
  });

  it("in-progress, low ratio (<45%) → '空いている目安'", () => {
    const info = crowdHintChip(snap({ completedNight: false, nowTotal: 10, peakTotal: 100 }));
    expect(info?.crowd).toBe("空いている目安");
    expect(info?.occupancyPercent).toBe(10);
  });
});
