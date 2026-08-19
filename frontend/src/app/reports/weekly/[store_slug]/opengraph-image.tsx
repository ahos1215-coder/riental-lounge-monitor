import { ImageResponse } from "next/og";
import { getStoreMetaBySlugStrict } from "@/app/config/stores";
import {
  REPORT_OG_CONTENT_TYPE,
  REPORT_OG_SIZE,
  reportOgImage,
} from "@/lib/og/reportOgImage";
import { jstWeekLabel } from "@/lib/og/weekLabel";

export const runtime = "edge";

export const size = REPORT_OG_SIZE;
export const contentType = REPORT_OG_CONTENT_TYPE;

type Props = {
  params: Promise<{ store_slug: string }>;
};

export default async function WeeklyReportOGImage({ params }: Props) {
  const { store_slug } = await params;
  const store = getStoreMetaBySlugStrict(store_slug);
  const label = store ? store.label : store_slug;
  const areaLabel = store ? store.areaLabel : "";

  const weekLabel = jstWeekLabel();

  return new ImageResponse(
    reportOgImage({
      background: "linear-gradient(135deg, #0a0a0f 0%, #0d1117 50%, #0a0f1e 100%)",
      decor: "radial-gradient(ellipse 80% 60% at 80% 120%, rgba(139,92,246,0.15) 0%, transparent 70%)",
      logoGradient: "linear-gradient(135deg, #8b5cf6, #6366f1)",
      badgeBackground: "rgba(139,92,246,0.15)",
      badgeBorder: "1px solid rgba(139,92,246,0.3)",
      badgeColor: "#c4b5fd",
      badgeLabel: "ML 予測 Weekly Report",
      dateLabel: weekLabel,
      title: label,
      titleStyle: { color: "white", fontSize: "64px", fontWeight: 700, lineHeight: 1.1 },
      subLabel: areaLabel,
      footerText: "週次の混雑傾向・ML 予測まとめ",
      footerAccent: "rgba(139,92,246,0.7)",
    }),
    { ...size },
  );
}
