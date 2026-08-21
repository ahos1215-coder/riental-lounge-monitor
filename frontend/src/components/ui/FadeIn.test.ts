/**
 * F13（2026-08-21 外部レビュー）の番犬テスト。
 *
 * 旧挙動: FadeIn は常に initial={{opacity:0, ...}} を渡すため、SSR HTML に opacity:0 が焼かれ、
 * hydration とアニメーション開始まで中身が見えなかった。トップの H1・ヒーロー説明文・主要 CTA が
 * これに包まれており、mobile lab LCP は 4.4〜4.5 秒（LCP 要素 = ヒーロー説明文）だった。
 *
 * ここでは「ファーストビュー用の immediate では初期スタイルが opacity:0 にならない」ことと、
 * 「既定（ページ下部の演出）は従来どおり」を固定する。
 * vitest は node 環境で DOM レンダラを持たないため、motion.div へ渡す initial を決める
 * 純粋関数 fadeInInitial を検証する。
 */
import { describe, expect, it } from "vitest";

import { fadeInInitial } from "./FadeIn";

describe("fadeInInitial", () => {
  it("既定（immediate なし）は従来どおり opacity:0 + 方向オフセットから始まる", () => {
    expect(fadeInInitial("up")).toEqual({ opacity: 0, x: 0, y: 24 });
    expect(fadeInInitial("down")).toEqual({ opacity: 0, x: 0, y: -24 });
    expect(fadeInInitial("left")).toEqual({ opacity: 0, x: 24, y: 0 });
    expect(fadeInInitial("right")).toEqual({ opacity: 0, x: -24, y: 0 });
    expect(fadeInInitial("none")).toEqual({ opacity: 0, x: 0, y: 0 });
    // 引数省略時の既定方向は "up"。
    expect(fadeInInitial()).toEqual({ opacity: 0, x: 0, y: 24 });
  });

  it("immediate=true なら initial は false（＝animate の値が初期スタイル＝SSR 時点で可視）", () => {
    expect(fadeInInitial("up", true)).toBe(false);
    expect(fadeInInitial("none", true)).toBe(false);
    expect(fadeInInitial("left", true)).toBe(false);
  });

  it("immediate=true では、どの方向でも opacity:0 を含むオブジェクトを返さない", () => {
    for (const d of ["up", "down", "left", "right", "none"] as const) {
      const initial = fadeInInitial(d, true);
      expect(typeof initial).not.toBe("object");
    }
  });
});
