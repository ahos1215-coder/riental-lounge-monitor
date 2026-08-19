import type { CSSProperties, ReactElement } from "react";

/**
 * 動的 OG 画像（/store/[id]・/reports/daily/[slug]・/reports/weekly/[slug]・/blog/[slug]）の
 * 共通レイアウト。4本とも「背景 → 装飾 → ブランド行 → バッジ+日付 → 見出し → フッター」という
 * 同じ骨格で、色・文言・見出しの大きさだけが違っていたのでここへ集約した。
 *
 * ImageResponse には「コンポーネント要素」ではなくこの関数の戻り値（＝ host 要素のツリー）を
 * そのまま渡すこと。要素ツリーが同一なら描画される PNG も同一になる
 * （lib/og/ogImage.snapshot.test.ts が 4 ルート分のツリーを固定している）。
 *
 * 注意（意図的でない可能性が高い既存のブレ。揃えると画像が変わるため現状維持し props にした）:
 *   - weekly だけ brandLetterSpacing が無い / ロゴのグラデーション向きが逆 / footerAlignItems が無い
 *   - weekly だけ背景の末尾が #0a0f1e（他3本は #0f0a1e）
 * 揃えるかどうかはオーナー判断。
 */
export type ReportOgImageProps = {
  /** ルート要素の背景（グラデーション文字列） */
  background: string;
  /** 背景装飾（radial-gradient 文字列） */
  decor: string;
  /** ロゴタイルのグラデーション */
  logoGradient: string;
  /** 「めぐりび · MEGRIBI」の letterSpacing（weekly のみ無し） */
  brandLetterSpacing?: string;
  /** 種別バッジ（背景・枠線・文字色・文言） */
  badgeBackground: string;
  badgeBorder: string;
  badgeColor: string;
  badgeLabel: string;
  /** バッジ右の日付ラベル（store / blog は無し） */
  dateLabel?: string;
  /** 見出しの上に置く1行（store のブランド名のみ） */
  eyebrow?: string;
  eyebrowStyle?: CSSProperties;
  /** 見出し本体。大きさ・行数クランプがページごとに違うのでスタイルごと受け取る。 */
  title: string;
  titleStyle: CSSProperties;
  /** 見出しの下の補足1行（エリア名。blog は無し） */
  subLabel?: string;
  footerText: string;
  /** フッター右「meguribi.jp」の色 */
  footerAccent: string;
  /** フッターの alignItems（weekly のみ無し） */
  footerAlignItems?: string;
};

export const REPORT_OG_SIZE = { width: 1200, height: 630 };
export const REPORT_OG_CONTENT_TYPE = "image/png";

export function reportOgImage(props: ReportOgImageProps): ReactElement {
  const {
    background,
    decor,
    logoGradient,
    brandLetterSpacing,
    badgeBackground,
    badgeBorder,
    badgeColor,
    badgeLabel,
    dateLabel,
    eyebrow,
    eyebrowStyle,
    title,
    titleStyle,
    subLabel,
    footerText,
    footerAccent,
    footerAlignItems,
  } = props;

  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        flexDirection: "column",
        background,
        fontFamily: "sans-serif",
        padding: "60px 80px",
        position: "relative",
      }}
    >
      {/* 背景装飾 */}
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          background: decor,
        }}
      />

      {/* サービス名 */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "12px",
          marginBottom: "auto",
        }}
      >
        <div
          style={{
            width: "40px",
            height: "40px",
            borderRadius: "10px",
            background: logoGradient,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: "20px",
          }}
        >
          ✦
        </div>
        <span
          style={{
            color: "rgba(255,255,255,0.5)",
            fontSize: "22px",
            ...(brandLetterSpacing ? { letterSpacing: brandLetterSpacing } : {}),
          }}
        >
          めぐりび · MEGRIBI
        </span>
      </div>

      {/* メインコンテンツ */}
      <div style={{ display: "flex", flexDirection: "column", marginTop: "32px" }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "12px",
            marginBottom: "16px",
          }}
        >
          <span
            style={{
              background: badgeBackground,
              border: badgeBorder,
              color: badgeColor,
              fontSize: "16px",
              padding: "4px 16px",
              borderRadius: "100px",
            }}
          >
            {badgeLabel}
          </span>
          {dateLabel === undefined ? null : (
            <span style={{ color: "rgba(255,255,255,0.3)", fontSize: "16px" }}>{dateLabel}</span>
          )}
        </div>

        {eyebrow === undefined ? null : <div style={eyebrowStyle}>{eyebrow}</div>}
        <div style={titleStyle}>{title}</div>
        {subLabel === undefined ? null : (
          <div style={{ color: "rgba(255,255,255,0.45)", fontSize: "26px", marginTop: "12px" }}>
            {subLabel}
          </div>
        )}
      </div>

      {/* フッター */}
      <div
        style={{
          marginTop: "auto",
          paddingTop: "32px",
          borderTop: "1px solid rgba(255,255,255,0.07)",
          display: "flex",
          justifyContent: "space-between",
          ...(footerAlignItems ? { alignItems: footerAlignItems } : {}),
        }}
      >
        <span style={{ color: "rgba(255,255,255,0.3)", fontSize: "18px" }}>{footerText}</span>
        <span style={{ color: footerAccent, fontSize: "18px" }}>meguribi.jp</span>
      </div>
    </div>
  );
}
