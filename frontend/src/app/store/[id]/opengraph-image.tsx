import { ImageResponse } from "next/og";
import { getStoreMetaBySlugStrict, BRAND_DISPLAY_LABEL } from "@/app/config/stores";
import {
  REPORT_OG_CONTENT_TYPE,
  REPORT_OG_SIZE,
  reportOgImage,
} from "@/lib/og/reportOgImage";

export const runtime = "edge";

export const size = REPORT_OG_SIZE;
export const contentType = REPORT_OG_CONTENT_TYPE;

type Props = {
  params: Promise<{ id: string }>;
};

export default async function StoreOGImage({ params }: Props) {
  const { id } = await params;
  const store = getStoreMetaBySlugStrict(id);
  const label = store ? store.label : id;
  const areaLabel = store ? store.areaLabel : "";
  // ブランド名（オリエンタルラウンジ / 相席屋 / JIS）を店舗ごとに正しく表示。
  const brandLabel = store ? BRAND_DISPLAY_LABEL[store.brand] : "オリエンタルラウンジ";

  return new ImageResponse(
    reportOgImage({
      background: "linear-gradient(135deg, #0a0a0f 0%, #0d1117 50%, #0f0a1e 100%)",
      decor: "radial-gradient(ellipse 80% 60% at 80% 20%, rgba(99,102,241,0.12) 0%, transparent 70%)",
      logoGradient: "linear-gradient(135deg, #6366f1, #8b5cf6)",
      brandLetterSpacing: "0.05em",
      badgeBackground: "rgba(16,185,129,0.15)",
      badgeBorder: "1px solid rgba(16,185,129,0.3)",
      badgeColor: "#6ee7b7",
      badgeLabel: "リアルタイム混雑情報",
      eyebrow: brandLabel,
      eyebrowStyle: {
        color: "white",
        fontSize: "64px",
        fontWeight: 700,
        lineHeight: 1.1,
        letterSpacing: "-0.02em",
      },
      title: label,
      titleStyle: {
        color: "white",
        fontSize: "72px",
        fontWeight: 700,
        lineHeight: 1.1,
        letterSpacing: "-0.02em",
        marginTop: "8px",
      },
      subLabel: areaLabel,
      footerText: "混雑傾向・男女比・ML 予測をまとめてチェック",
      footerAccent: "rgba(99,102,241,0.7)",
      footerAlignItems: "center",
    }),
    { ...size },
  );
}
