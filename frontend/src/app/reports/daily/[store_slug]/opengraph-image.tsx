import { ImageResponse } from "next/og";
import { getStoreMetaBySlugStrict } from "@/app/config/stores";
import {
  REPORT_OG_CONTENT_TYPE,
  REPORT_OG_SIZE,
  reportOgImage,
} from "@/lib/og/reportOgImage";

export const runtime = "edge";

export const size = REPORT_OG_SIZE;
export const contentType = REPORT_OG_CONTENT_TYPE;

type Props = {
  params: Promise<{ store_slug: string }>;
};

export default async function DailyReportOGImage({ params }: Props) {
  const { store_slug } = await params;
  const store = getStoreMetaBySlugStrict(store_slug);
  const label = store ? store.label : store_slug;
  const areaLabel = store ? store.areaLabel : "";

  const today = new Date().toLocaleDateString("ja-JP", {
    timeZone: "Asia/Tokyo",
    year: "numeric",
    month: "long",
    day: "numeric",
  });

  return new ImageResponse(
    reportOgImage({
      background: "linear-gradient(135deg, #0a0a0f 0%, #0d1117 50%, #0f0a1e 100%)",
      decor: "radial-gradient(ellipse 80% 60% at 20% 120%, rgba(99,102,241,0.15) 0%, transparent 70%)",
      logoGradient: "linear-gradient(135deg, #6366f1, #8b5cf6)",
      brandLetterSpacing: "0.05em",
      badgeBackground: "rgba(99,102,241,0.15)",
      badgeBorder: "1px solid rgba(99,102,241,0.3)",
      badgeColor: "#a5b4fc",
      badgeLabel: "ML 予測 Daily Report",
      dateLabel: today,
      title: label,
      titleStyle: {
        color: "white",
        fontSize: "64px",
        fontWeight: 700,
        lineHeight: 1.1,
        letterSpacing: "-0.02em",
      },
      subLabel: areaLabel,
      footerText: "混雑傾向・男女比・ML 予測をまとめてチェック",
      footerAccent: "rgba(99,102,241,0.7)",
      footerAlignItems: "center",
    }),
    { ...size },
  );
}
