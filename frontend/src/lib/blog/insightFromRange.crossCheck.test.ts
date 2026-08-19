// frontend/src/lib/blog/insightFromRange.crossCheck.test.ts
//
// 番犬（C-09 / C-08）: 夜窓インサイトの計算は 2 つある。
//   - TS 版: src/lib/blog/insightFromRange.ts（LINE / 緊急 cron が使う）
//   - mjs 版: scripts/lib/insightCore.mjs（GHA generate-public-facts.yml が 09:30 JST に使う）
// mjs は素の `node` 実行のため TS を import できず、やむを得ず並行実装になっている。
// 片方だけ直すと Public Facts と LINE 下書きの数値が食い違うので、ここで出力一致を固定する。
//
// このテストは C-08（キー集合の定数化・collectPoints の実装統合）の値等価テストも兼ねる:
// mjs 側は C-08 のリファクタ対象外なので、TS 側だけ値が変わればここが落ちる。
import { describe, expect, it } from "vitest";
import {
  collectPoints,
  collectPointsWithGender,
  computeInsight,
  nightWindowIso,
} from "./insightFromRange";
import * as mjs from "../../../scripts/lib/insightCore.mjs";

const RANGE_OPTS = {
  totalKeys: ["total"],
  menKeys: ["men", "male", "m"],
  womenKeys: ["women", "female", "f"],
};
const FORECAST_OPTS = {
  totalKeys: ["total_pred", "total"],
  menKeys: ["men_pred", "men", "male", "m"],
  womenKeys: ["women_pred", "women", "female", "f"],
};

const YMD = "2026-08-18";

/** 実測行: UTC / JST / naive / マイクロ秒 / 窓外 / 男女欠損 を混ぜる */
const RANGE_ROWS: unknown[] = [
  { ts: "2026-08-18T09:00:00Z", men: 5, women: 4 }, // 18:00 JST（窓外）
  { ts: "2026-08-18T10:30:00Z", men: 40, women: 35 }, // 19:30 JST
  { ts: "2026-08-18T21:00:00+09:00", total: 130 }, // total のみ
  { ts: "2026-08-18 22:15:00", men: 50, women: 45 }, // naive（+09:00 とみなす）
  { ts: "2026-08-18T14:00:00.123456Z", men: 30 }, // 23:00 JST・women 欠損 → total 不能
  { ts: "2026-08-18T15:30:00.987654Z", male: 20, female: 18 }, // 別名キー
  { ts: "2026-08-19T05:30:00+09:00", men: 1, women: 1 }, // 窓外（翌05:30）
  { men: 1, women: 1 }, // ts なし
  null,
  "not-an-object",
];

/** 予測行（前日分＝+1day シフトが要るケースを含む） */
const FORECAST_ROWS: unknown[] = [
  { ts: "2026-08-17T20:00:00+09:00", total_pred: 60 },
  { ts: "2026-08-17T22:00:00+09:00", men_pred: 55, women_pred: 50 },
  { ts: "2026-08-17T23:45:00+09:00", total_pred: 95 },
];

describe("insightFromRange（TS）と scripts/lib/insightCore.mjs の出力一致", () => {
  it("nightWindowIso が同一", () => {
    expect(nightWindowIso(YMD)).toEqual(mjs.nightWindowIso(YMD));
    expect(nightWindowIso(YMD)).toEqual({
      from: "2026-08-18T19:00:00+09:00",
      to: "2026-08-19T05:00:00+09:00",
      label: "Tonight",
    });
    // 月末またぎも一致
    expect(nightWindowIso("2026-08-31")).toEqual(mjs.nightWindowIso("2026-08-31"));
  });

  it("collectPoints（実測キー）が同一", () => {
    const { from, to } = nightWindowIso(YMD);
    const ts = collectPoints(RANGE_ROWS, from, to, RANGE_OPTS);
    const js = mjs.collectPoints(RANGE_ROWS.filter((r) => r && typeof r === "object"), from, to, RANGE_OPTS);
    expect(ts.map((p) => [p.dt.toISOString(), p.total])).toEqual(
      js.map((p: { dt: Date; total: number | null }) => [p.dt.toISOString(), p.total]),
    );
    // 窓外・ts不正・男女片方欠損は落ちる
    expect(ts.map((p) => p.total)).toEqual([75, 130, 95, 38]);
  });

  it("collectPoints（予測キー・+1day シフト）が同一", () => {
    const { from, to } = nightWindowIso(YMD);
    const opts = { ...FORECAST_OPTS, shiftDays: 1 };
    const ts = collectPoints(FORECAST_ROWS, from, to, opts);
    const js = mjs.collectPoints(FORECAST_ROWS, from, to, opts);
    expect(ts.map((p) => [p.dt.toISOString(), p.total])).toEqual(
      js.map((p: { dt: Date; total: number | null }) => [p.dt.toISOString(), p.total]),
    );
    expect(ts.map((p) => p.total)).toEqual([60, 105, 95]);
    // シフト無しでは前日の点は窓に入らない
    expect(collectPoints(FORECAST_ROWS, from, to, FORECAST_OPTS)).toEqual([]);
  });

  it("computeInsight が同一（120/80 の絶対閾値・ピーク/空き時刻）", () => {
    const { from, to } = nightWindowIso(YMD);
    const pts = collectPoints(RANGE_ROWS, from, to, RANGE_OPTS);
    expect(computeInsight(pts)).toEqual(mjs.computeInsight(pts));
    expect(computeInsight(pts)).toEqual({
      peak_time: "21:00",
      avoid_time: "00:30",
      crowd_label: "混み",
    });
    // 空配列
    expect(computeInsight([])).toEqual(mjs.computeInsight([]));
    // 閾値の境界（80 未満＝空き / 80＝ほどよい / 120＝混み）
    for (const total of [0, 79, 80, 119, 120, 500]) {
      const one = [{ dt: new Date("2026-08-18T21:00:00+09:00"), total }];
      expect(computeInsight(one), String(total)).toEqual(mjs.computeInsight(one));
    }
  });

  it("collectPointsWithGender は collectPoints の上位互換（dt/total が一致）", () => {
    const { from, to } = nightWindowIso(YMD);
    const plain = collectPoints(RANGE_ROWS, from, to, RANGE_OPTS);
    const withGender = collectPointsWithGender(RANGE_ROWS, from, to, RANGE_OPTS);
    expect(withGender.map(({ dt, total }) => ({ dt, total }))).toEqual(plain);
    expect(withGender.map((p) => [p.men, p.women])).toEqual([
      [40, 35],
      [null, null],
      [50, 45],
      [20, 18],
    ]);
  });

  // 既知の落とし穴（両実装で同じ挙動なので"仕様として固定"する。直すなら両方同時に）:
  // ts が日付として解釈できない行は parseTimestamp が Invalid Date を返し、
  // NaN 比較が常に false になるため夜窓フィルタをすり抜けて集計に混ざる。
  it("解釈できない ts の行の扱いも両実装で同じ（すり抜ける）", () => {
    const { from, to } = nightWindowIso(YMD);
    const rows = [{ ts: "bad", men: 1, women: 1 }];
    const ts = collectPoints(rows, from, to, RANGE_OPTS);
    const js = mjs.collectPoints(rows, from, to, RANGE_OPTS);
    expect(ts.map((p) => p.total)).toEqual(js.map((p: { total: number | null }) => p.total));
    expect(ts.map((p) => Number.isNaN(p.dt.getTime()))).toEqual(
      js.map((p: { dt: Date }) => Number.isNaN(p.dt.getTime())),
    );
    expect(ts).toHaveLength(1);
  });

  it("pickArray（封筒ほどき）も同一", () => {
    for (const body of [
      [{ ts: "x" }],
      { rows: [{ ts: "x" }] },
      { data: [{ ts: "x" }] },
      {},
      null,
    ]) {
      expect(mjs.pickArray(body)).toEqual(
        Array.isArray(body)
          ? body
          : ((body as { rows?: unknown[]; data?: unknown[] } | null)?.rows ??
            (body as { data?: unknown[] } | null)?.data ??
            []),
      );
    }
  });
});
