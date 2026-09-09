// 番犬テスト: 一時的な取得失敗で「良品カード」を消さないこと。
//
// 直前の修正（取得失敗を 0 人と描かない）を入れた際、失敗時に既存カードを丸ごと
// 空カードで置換していた。呼び出し元 4 箇所のうち 2 箇所は単発 fetch の失敗と例外
// （一瞬の回線断・JSON 不正）なので、SSR で正しく出ていたカードが裏側更新中の
// わずかな失敗だけで「混雑データを取得できていません」に化ける＝平常時の退行だった。
// ここでは「stats がある店は上書きしない／無い店だけ unavailable」を固定する。
import { describe, expect, it } from "vitest";

import { withCardUnavailable } from "./storeCardUnavailable";
import type { StoreRealtimeCard } from "./stores-list-client";

function goodCard(slug: string, over: Partial<StoreRealtimeCard> = {}): StoreRealtimeCard {
  return {
    slug,
    stats: {
      menCount: 13,
      womenCount: 10,
      nowTotal: 23,
      peakPredTotal: 40,
      genderRatio: "13:10",
      crowdLevel: "やや混雑",
      recommendLabel: "22:30ごろ",
    },
    sparkline: [1, 2, 3],
    sparklineTimes: [1, 2, 3],
    sparklineMen: [1, 1, 2],
    sparklineWomen: [0, 1, 1],
    sparklineGenderTimes: [1, 2, 3],
    forecastPending: false,
    megribiScore: 0.7,
    latestActualTs: "2026-09-09T21:05:00+09:00",
    ...over,
  };
}

describe("withCardUnavailable", () => {
  it("良品カード（stats あり）は一時的な失敗で消えない", () => {
    const prev = { shibuya: goodCard("shibuya") };
    const next = withCardUnavailable(prev, "shibuya");

    // 数値・sparkline・鮮度の元 ts がすべて残っていること（フォールバック表示が効く）
    expect(next.shibuya.stats).toEqual(prev.shibuya.stats);
    expect(next.shibuya.sparkline).toEqual([1, 2, 3]);
    expect(next.shibuya.sparklineMen).toEqual([1, 1, 2]);
    expect(next.shibuya.sparklineWomen).toEqual([0, 1, 1]);
    expect(next.shibuya.latestActualTs).toBe("2026-09-09T21:05:00+09:00");
    expect(next.shibuya.megribiScore).toBe(0.7);
    // 数値が出ている以上「取得できていません」は立てない
    expect(next.shibuya.dataUnavailable).toBeUndefined();
    // 変更が無いので state の同一性も保つ（無駄な再レンダーを起こさない）
    expect(next).toBe(prev);
  });

  it("良品カードが予測待ちだった場合は forecastPending だけ下ろす（「取得中」で固まらない）", () => {
    const prev = { shibuya: goodCard("shibuya", { forecastPending: true }) };
    const next = withCardUnavailable(prev, "shibuya");

    expect(next.shibuya.forecastPending).toBe(false);
    expect(next.shibuya.stats).toEqual(prev.shibuya.stats);
    expect(next.shibuya.dataUnavailable).toBeUndefined();
  });

  it("まだ人数が無い店だけ dataUnavailable の空カードにする", () => {
    const next = withCardUnavailable({}, "ay_chiba");
    expect(next.ay_chiba.stats).toBeUndefined();
    expect(next.ay_chiba.dataUnavailable).toBe(true);
    expect(next.ay_chiba.forecastPending).toBe(false);
    expect(next.ay_chiba.sparkline).toEqual([]);
    expect(next.ay_chiba.megribiScore).toBeNull();
  });

  it("stats が無いカードの megribiScore は引き継ぐ（先に届いたスコアを捨てない）", () => {
    const prev: Record<string, StoreRealtimeCard> = {
      ay_chiba: {
        slug: "ay_chiba",
        sparkline: [],
        sparklineMen: [],
        sparklineWomen: [],
        megribiScore: 0.42,
      },
    };
    const next = withCardUnavailable(prev, "ay_chiba");
    expect(next.ay_chiba.dataUnavailable).toBe(true);
    expect(next.ay_chiba.megribiScore).toBe(0.42);
  });

  it("他店のカードには触らない", () => {
    const prev = { shibuya: goodCard("shibuya"), ay_chiba: goodCard("ay_chiba") };
    const next = withCardUnavailable(prev, "nagoya");
    expect(next.shibuya).toBe(prev.shibuya);
    expect(next.ay_chiba).toBe(prev.ay_chiba);
    expect(next.nagoya.dataUnavailable).toBe(true);
  });
});
