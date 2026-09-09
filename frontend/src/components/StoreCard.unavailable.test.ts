// 番犬テスト: 取得できていない店のカードに数字を出さないこと（描画まで含めて固定する）。
//
// 2026-09-09 の Supabase 402 事故で、/stores の全 42 店が「男性0 / 女性0 / 計0」という
// 誤情報を 3 日半出し続けた。データ側の読み分け（lib/range/rangeMultiStatus）だけでなく、
// カードが実際に 0 を描かないところまでを固定する。
//
// vitest は environment:"node" かつ *.test.ts のみ（JSX 不可）なので、
// createElement + renderToStaticMarkup で HTML を得る。useEffect は走らないが、
// ここで見たいのは初期描画の中身だけ。
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { StoreCard } from "./StoreCard";

const BASE = {
  slug: "shibuya",
  label: "オリエンタルラウンジ 渋谷",
  brandLabel: "ORIENTAL LOUNGE",
  areaLabel: "渋谷",
};

function render(props: Record<string, unknown>): string {
  return renderToStaticMarkup(createElement(StoreCard, { ...BASE, ...props } as never));
}

describe("StoreCard の dataUnavailable", () => {
  it("取得できていないカードは人数を1つも描かず、理由を出す", () => {
    // 取得失敗時に呼び出し側が渡す形（stats を渡さない + dataUnavailable:true）
    const html = render({ dataUnavailable: true, sparkline: [], sparklineMen: [], sparklineWomen: [] });
    expect(html).toContain("混雑データを取得できていません");
    expect(html).not.toContain("男性 0");
    expect(html).not.toContain("女性 0");
    expect(html).not.toContain("計 0");
    // 「0人」に見える数字が本当に1つも無いこと（人数・％・比のいずれも）
    expect(html).not.toMatch(/男性[^<]*\d/);
    expect(html).not.toMatch(/女性[^<]*\d/);
  });

  it("正常時（stats あり）の描画は dataUnavailable を渡さない限り従来どおり", () => {
    const stats = {
      menCount: 13,
      womenCount: 10,
      nowTotal: 23,
      peakPredTotal: 30,
      genderRatio: "13:10",
      crowdLevel: "ほどよい",
      recommendLabel: "22:00ごろ",
    };
    const html = render({ stats });
    expect(html).toContain("男性 13");
    expect(html).toContain("女性 10");
    expect(html).toContain("計 23");
    expect(html).not.toContain("混雑データを取得できていません");
  });

  it("本当に 0 人を観測した店は従来どおり 0 を出す（欠測と混同しない）", () => {
    const stats = {
      menCount: 0,
      womenCount: 0,
      nowTotal: 0,
      peakPredTotal: 0,
      genderRatio: "0:0",
      crowdLevel: "空いている",
      recommendLabel: "21:00ごろ",
    };
    const html = render({ stats });
    expect(html).toContain("男性 0");
    expect(html).toContain("計 0");
    expect(html).not.toContain("混雑データを取得できていません");
  });

  it("事故の再現: range_multi が全店 ok:false でも、カードに 0 人が出ない", async () => {
    const { buildInitialStoreCards } = await import("@/app/stores/initialStoreCards");
    const targets = [{ slug: "shibuya" }];
    const cards = buildInitialStoreCards(
      targets,
      { shibuya: { ok: false, error: "upstream-supabase", rows: [] } },
      new Map(),
    );
    const card = cards.shibuya;
    const html = render({
      stats: card.stats,
      sparkline: card.sparkline,
      sparklineMen: card.sparklineMen,
      sparklineWomen: card.sparklineWomen,
      forecastPending: card.forecastPending,
      dataUnavailable: card.dataUnavailable,
    });
    expect(html).toContain("混雑データを取得できていません");
    expect(html).not.toMatch(/男性[^<]*\d/);
    expect(html).not.toContain("計 0");
  });

  it("読み込み中（isLoading）はスケルトンのままで、取得失敗の文言は出さない", () => {
    const html = render({ isLoading: true, dataUnavailable: true });
    expect(html).not.toContain("混雑データを取得できていません");
    expect(html).toContain("animate-pulse");
  });
});
