import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

/**
 * 所見1: contact/page.tsx の href が https://forms.gle/PLACEHOLDER のまま本番公開されており
 * クリックすると404になっていた。プレースホルダーURLが二度と紛れ込まないことと、
 * URL未設定時は非リンクの「準備中」表示になっていることをソース上で確認する
 * （このリポジトリに React コンポーネントの DOM レンダリングテスト基盤が無いため、
 * ソーステキストに対する回帰チェックとする）。
 */
describe("contact/page.tsx — 壊れたフォームリンクを出さない", () => {
  const source = readFileSync(
    fileURLToPath(new URL("./page.tsx", import.meta.url)),
    "utf-8",
  );

  it("プレースホルダーURL forms.gle/PLACEHOLDER を含まない", () => {
    expect(source).not.toContain("forms.gle/PLACEHOLDER");
  });

  it("個人メールアドレスを含まない", () => {
    expect(source).not.toMatch(/[\w.+-]+@[\w-]+\.[\w.-]+/);
  });

  it("CONTACT_FORM_URL が空のときに備えた「準備中」の非リンク表示を持つ", () => {
    expect(source).toContain("CONTACT_FORM_URL");
    expect(source).toContain("準備中");
  });
});
