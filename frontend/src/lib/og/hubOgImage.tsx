import type { ReactElement } from "react";

/**
 * ハブページ（/ , /stores, /reports, /blog）の OG 画像の共通レイアウト。
 *
 * 4本の opengraph-image.tsx は alt・関数名・サブコピー1行を除いてバイト一致だったので、
 * 差分のサブコピーだけを引数にして1箇所にまとめた。
 *
 * ImageResponse には「コンポーネント要素」ではなくこの関数の戻り値（＝ host 要素のツリー）を
 * そのまま渡すこと。要素ツリーが同一であれば描画される PNG も同一になる
 * （lib/og/ogImage.snapshot.test.ts がツリーを固定している）。
 */
export function hubOgImage(subcopy: string): ReactElement {
  return (
    <div
      style={{
        height: "100%",
        width: "100%",
        display: "flex",
        flexDirection: "column",
        alignItems: "flex-start",
        justifyContent: "center",
        background: "linear-gradient(135deg, #050508 0%, #1e1b4b 45%, #0f172a 100%)",
        padding: 72,
      }}
    >
      <div
        style={{
          fontSize: 26,
          color: "#a5b4fc",
          letterSpacing: "0.35em",
          textTransform: "uppercase",
          fontWeight: 600,
        }}
      >
        Oriental Lounge
      </div>
      <div style={{ marginTop: 20, fontSize: 80, fontWeight: 800, color: "#ffffff", letterSpacing: "-0.03em" }}>
        めぐりび
      </div>
      <div
        style={{
          marginTop: 20,
          fontSize: 30,
          color: "rgba(255,255,255,0.78)",
          maxWidth: 920,
          lineHeight: 1.35,
        }}
      >
        {subcopy}
      </div>
    </div>
  );
}

/** ハブ OG 画像4本で共通のメタ（各ルートが再 export する）。 */
export const HUB_OG_SIZE = { width: 1200, height: 630 };
export const HUB_OG_CONTENT_TYPE = "image/png";
