import { ImageResponse } from "next/og";
import { getPostBySlug } from "@/lib/blog/content";

// フロントマター（content/blog/*.mdx）を fs で読むため nodejs ランタイム必須（edge では fs 不可）。
export const runtime = "nodejs";

export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

/** タイトル未取得時に slug 由来の英字を出さないためのブランド既定値。 */
const BLOG_OG_TITLE_FALLBACK = "めぐりび｜相席ラウンジ攻略ブログ";

/**
 * OG 画像に描画するブログタイトルを決める純関数。
 * - フロントマターの実タイトル（例:「渋谷店：今夜の狙い目」）を最優先で使う。
 * - 未設定/取得失敗、または getPostBySlug が title 欠落時に slug をそのまま返してきた場合は、
 *   機械整形した英字（旧バグ: "Shibuya Tonight 20251220"）ではなくブランド既定値へフォールバック。
 * - 長い日本語タイトルは maxLen で丸め、末尾に「…」を付けて画像内で破綻させない。
 */
export function resolveBlogOgTitle(
  rawTitle: string | null | undefined,
  slug: string,
  maxLen = 44,
): string {
  const trimmed = typeof rawTitle === "string" ? rawTitle.trim() : "";
  const isMissing = trimmed.length === 0 || trimmed === slug.trim();
  const base = isMissing ? BLOG_OG_TITLE_FALLBACK : trimmed;
  return base.length > maxLen ? `${base.slice(0, maxLen - 1)}…` : base;
}

type Props = {
  params: Promise<{ slug: string }>;
};

export default async function BlogOGImage({ params }: Props) {
  const { slug } = await params;
  let frontmatterTitle: string | null = null;
  try {
    frontmatterTitle = getPostBySlug(slug)?.title ?? null;
  } catch {
    // フロントマター読み取り失敗時も画像生成は落とさず、既定タイトルで描画する。
    frontmatterTitle = null;
  }
  const title = resolveBlogOgTitle(frontmatterTitle, slug);

  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          background: "linear-gradient(135deg, #0a0a0f 0%, #0d1117 50%, #0f0a1e 100%)",
          fontFamily: "sans-serif",
          padding: "60px 80px",
          position: "relative",
        }}
      >
        <div
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background:
              "radial-gradient(ellipse 80% 60% at 50% 80%, rgba(139,92,246,0.12) 0%, transparent 70%)",
          }}
        />

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
              background: "linear-gradient(135deg, #6366f1, #8b5cf6)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: "20px",
            }}
          >
            ✦
          </div>
          <span style={{ color: "rgba(255,255,255,0.5)", fontSize: "22px", letterSpacing: "0.05em" }}>
            めぐりび · MEGRIBI
          </span>
        </div>

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
                background: "rgba(139,92,246,0.15)",
                border: "1px solid rgba(139,92,246,0.3)",
                color: "#c4b5fd",
                fontSize: "16px",
                padding: "4px 16px",
                borderRadius: "100px",
              }}
            >
              Blog
            </span>
          </div>

          <div
            style={{
              display: "-webkit-box",
              color: "white",
              fontSize: "52px",
              fontWeight: 700,
              lineHeight: 1.25,
              letterSpacing: "-0.02em",
              maxWidth: "900px",
              WebkitBoxOrient: "vertical",
              WebkitLineClamp: 3,
              overflow: "hidden",
            }}
          >
            {title}
          </div>
        </div>

        <div
          style={{
            marginTop: "auto",
            paddingTop: "32px",
            borderTop: "1px solid rgba(255,255,255,0.07)",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
          }}
        >
          <span style={{ color: "rgba(255,255,255,0.3)", fontSize: "18px" }}>
            ML 予測レポート
          </span>
          <span style={{ color: "rgba(99,102,241,0.7)", fontSize: "18px" }}>
            meguribi.jp
          </span>
        </div>
      </div>
    ),
    { ...size },
  );
}
