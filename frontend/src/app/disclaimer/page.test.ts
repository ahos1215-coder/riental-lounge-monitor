import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

/**
 * 所見2: disclaimer/page.tsx が実装と食い違う記述をしていた。
 * - 「XGBoost」→ 実際は LightGBM（CLAUDE.md §4-1、model_xgb.py は名前だけ残った移行済みファイル）
 * - 「人数の推計値を算出・表示するものではありません」→ 相席屋は内部で人数を逆算推定しており
 *   （%を保存用に人数へ変換）、利用者へは%のみを見せている、というのが実態（CLAUDE.md §4-3）。
 * ソースの回帰チェックとして、誤った記述が戻らないことを確認する。
 */
describe("disclaimer/page.tsx — 実装と矛盾する記述を含まない", () => {
  const source = readFileSync(
    fileURLToPath(new URL("./page.tsx", import.meta.url)),
    "utf-8",
  );

  it("XGBoost という誤った表記を含まない", () => {
    expect(source).not.toContain("XGBoost");
  });

  it("実際のモデル LightGBM に言及している", () => {
    expect(source).toContain("LightGBM");
  });

  it("相席屋の%表示が独自推計の参考値であることに言及している", () => {
    expect(source).toContain("独自に推計した参考値");
  });

  it("内部的に人数へ逆算していることを隠さず記載している", () => {
    expect(source).toMatch(/人数を逆算/);
  });
});
