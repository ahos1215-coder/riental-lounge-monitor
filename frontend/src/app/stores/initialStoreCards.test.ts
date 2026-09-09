// 番犬テスト: /stores の SSR カードが、取得できなかった店に「0 人」を出さないこと。
//
// 2026-09-09 の Supabase 402 事故で全 42 店が「男性0 / 女性0 / 計0」と表示された経路の
// サーバー側半分（page.tsx の初期スナップショット）。クライアント側の同じ読み分けは
// lib/range/rangeMultiStatus.test.ts が固定している。
import { describe, expect, it } from "vitest";

import { buildInitialStoreCards } from "./initialStoreCards";

const TARGETS = [{ slug: "shibuya" }, { slug: "ay_chiba" }];

const ROWS = [
  { ts: "2026-09-09T21:00:00+09:00", men: 12, women: 9, total: 21 },
  { ts: "2026-09-09T21:05:00+09:00", men: 13, women: 10, total: 23 },
];

describe("buildInitialStoreCards", () => {
  it("正常時は従来どおり最新行の人数でカードを作る", () => {
    const cards = buildInitialStoreCards(
      TARGETS,
      { shibuya: { rows: ROWS }, ay_chiba: { rows: ROWS } },
      new Map([["shibuya", 0.7]]),
    );
    expect(cards.shibuya.stats).toMatchObject({
      menCount: 13,
      womenCount: 10,
      nowTotal: 23,
      genderRatio: "13:10",
      crowdLevel: "取得中",
    });
    expect(cards.shibuya.forecastPending).toBe(true);
    expect(cards.shibuya.dataUnavailable).toBeUndefined();
    expect(cards.shibuya.megribiScore).toBe(0.7);
    expect(cards.ay_chiba.megribiScore).toBeNull();
  });

  it("その店だけ上流エラーなら stats を作らず dataUnavailable にする（0 人と表示しない）", () => {
    const cards = buildInitialStoreCards(
      TARGETS,
      {
        shibuya: { rows: ROWS },
        // 本番の部分障害エントリ（oriental/routes/data_range.py の _fetch_slug）。
        // rows は空でも来るが、ここでは **あえて中身のある行を入れる**。
        // rows:[] のままだと no-rows 分岐でも同じ結果になり、ok:false の判定行を
        // 消してもテストが緑のままだった（検問として機能していなかった）。
        ay_chiba: { ok: false, error: "upstream-supabase", rows: ROWS },
      },
      new Map(),
    );
    expect(cards.ay_chiba.stats).toBeUndefined();
    expect(cards.ay_chiba.dataUnavailable).toBe(true);
    // 予測の「取得中」も出さない（人数が無いのに待たせない）
    expect(cards.ay_chiba.forecastPending).toBe(false);
    // 巻き添えにしない: 取れている店は従来どおり
    expect(cards.shibuya.stats?.nowTotal).toBe(23);
  });

  it("全店が上流エラーでも、どのカードにも 0 人が現れない（2026-09-09 の再現）", () => {
    // rows に中身を入れて「ok:false を見ているか」だけを問う（rows:[] だと no-rows でも通る）。
    const outage = Object.fromEntries(
      TARGETS.map((t) => [t.slug, { ok: false, error: "upstream-supabase", rows: ROWS }]),
    );
    const cards = buildInitialStoreCards(TARGETS, outage, new Map());
    for (const t of TARGETS) {
      expect(cards[t.slug].stats, `${t.slug} に人数を作ってはいけない`).toBeUndefined();
      expect(cards[t.slug].dataUnavailable).toBe(true);
    }
  });

  it("行はあるが最新行の人数が全部欠損なら dataUnavailable（0 人と表示しない）", () => {
    const cards = buildInitialStoreCards(
      TARGETS,
      {
        shibuya: { rows: ROWS },
        ay_chiba: { rows: [{ ts: "2026-09-09T21:05:00+09:00", men: null, women: null, total: null }] },
      },
      new Map(),
    );
    expect(cards.ay_chiba.stats).toBeUndefined();
    expect(cards.ay_chiba.dataUnavailable).toBe(true);
    expect(cards.shibuya.stats?.nowTotal).toBe(23);
  });

  it("by_slug 自体が空・エントリ欠落でも dataUnavailable のカードになる", () => {
    const cards = buildInitialStoreCards(TARGETS, {}, new Map());
    expect(cards.shibuya.dataUnavailable).toBe(true);
    expect(cards.shibuya.stats).toBeUndefined();
    expect(buildInitialStoreCards(TARGETS, undefined, new Map()).ay_chiba.dataUnavailable).toBe(
      true,
    );
  });
});
