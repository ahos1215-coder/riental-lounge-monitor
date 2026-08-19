// frontend/src/app/hooks/useStorePreviewData.constants.test.ts
//
// C-11（到達不能フォールバックの撤去）の番犬テスト。
//
// useStorePreviewData には `RANGE_LIMIT_BY_MODE[rangeMode] ?? 400` /
// `FORECAST_RETRY_DELAYS_MS[attempt] ?? 12_000` / `?? 45_000` という到達不能な
// フォールバックが残っていた。撤去の安全性は「テーブルがモードを網羅している」
// 「リトライ配列が FORECAST_MAX_RETRIES 分ある」の2点に依存するので、
// その前提をここで固定する（前提が崩れたらこのテストが落ちる）。
import { describe, expect, it } from "vitest";

import {
  FORECAST_MAX_RETRIES,
  FORECAST_RETRY_DELAYS_MS,
  RANGE_LIMIT_BY_MODE,
  type PreviewRangeMode,
} from "./storePreviewSnapshot";

const ALL_MODES: PreviewRangeMode[] = ["today", "yesterday", "lastWeek", "custom"];

describe("RANGE_LIMIT_BY_MODE は全モードを網羅している（?? フォールバック不要）", () => {
  it("キー集合が PreviewRangeMode と一致する", () => {
    expect(Object.keys(RANGE_LIMIT_BY_MODE).sort()).toEqual([...ALL_MODES].sort());
  });

  for (const mode of ALL_MODES) {
    it(`${mode} は正の有限数を返す`, () => {
      const limit = RANGE_LIMIT_BY_MODE[mode];
      expect(Number.isFinite(limit)).toBe(true);
      expect(limit).toBeGreaterThan(0);
    });
  }

  it("値が変わっていない（today は初速重視で軽め）", () => {
    expect(RANGE_LIMIT_BY_MODE).toEqual({
      today: 240,
      yesterday: 1200,
      lastWeek: 1200,
      custom: 1200,
    });
  });
});

describe("FORECAST_RETRY_DELAYS_MS は FORECAST_MAX_RETRIES 回分ある（?? フォールバック不要）", () => {
  it("上限がそのまま配列長", () => {
    expect(FORECAST_MAX_RETRIES).toBe(FORECAST_RETRY_DELAYS_MS.length);
  });

  it("attempt < FORECAST_MAX_RETRIES の全 index で有限数が取れる", () => {
    for (let attempt = 0; attempt < FORECAST_MAX_RETRIES; attempt += 1) {
      const delay = FORECAST_RETRY_DELAYS_MS[attempt];
      expect(Number.isFinite(delay)).toBe(true);
      expect(delay).toBeGreaterThan(0);
    }
  });

  it("待ち時間が変わっていない（合計 24 秒。65s→24s 短縮後の値）", () => {
    expect([...FORECAST_RETRY_DELAYS_MS]).toEqual([4_000, 8_000, 12_000]);
    expect(FORECAST_RETRY_DELAYS_MS.reduce((a, b) => a + b, 0)).toBe(24_000);
  });
});
