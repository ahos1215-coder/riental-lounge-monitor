import { ImageResponse } from "next/og";
import { getStoreMetaBySlugStrict } from "@/app/config/stores";

export const runtime = "edge";

export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

type Props = {
  params: Promise<{ store_slug: string }>;
};

export default async function WeeklyReportOGImage({ params }: Props) {
  const { store_slug } = await params;
  const store = getStoreMetaBySlugStrict(store_slug);
  const label = store ? store.label : store_slug;
  const areaLabel = store ? store.areaLabel : "";

  const weekLabel = (() => {
    const d = new Date();
    const day = d.getDay();
    const mon = new Date(d);
    mon.setDate(d.getDate() - ((day + 6) % 7));
    return `${mon.getFullYear()}年${mon.getMonth() + 1}月${mon.getDate()}日週`;
  })();

  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          background: "linear-gradient(135deg, #0a0a0f 0%, #0d1117 50%, #0a0f1e 100%)",
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
              "radial-gradient(ellipse 80% 60% at 80% 120%, rgba(139,92,246,0.15) 0%, transparent 70%)",
          }}
        />
        <div style={{ display: "flex", alignItems: "center", gap: "12px", marginBottom: "auto" }}>
          <div
            style={{
              width: "40px",
              height: "40px",
              borderRadius: "10px",
              background: "linear-gradient(135deg, #8b5cf6, #6366f1)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: "20px",
            }}
          >
            ✦
          </div>
          <span style={{ color: "rgba(255,255,255,0.5)", fontSize: "22px" }}>めぐりび · MEGRIBI</span>
        </div>
        <div style={{ display: "flex", flexDirection: "column", marginTop: "32px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "12px", marginBottom: "16px" }}>
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
              AI 予測 Weekly Report
            </span>
            <span style={{ color: "rgba(255,255,255,0.3)", fontSize: "16px" }}>{weekLabel}</span>
          </div>
          <div style={{ color: "white", fontSize: "64px", fontWeight: 700, lineHeight: 1.1 }}>
            {label}
          </div>
          <div style={{ color: "rgba(255,255,255,0.45)", fontSize: "26px", marginTop: "12px" }}>
            {areaLabel}
          </div>
        </div>
        <div
          style={{
            marginTop: "auto",
            paddingTop: "32px",
            borderTop: "1px solid rgba(255,255,255,0.07)",
            display: "flex",
            justifyContent: "space-between",
          }}
        >
          <span style={{ color: "rgba(255,255,255,0.3)", fontSize: "18px" }}>
            週次の混雑傾向・ML 予測まとめ
          </span>
          <span style={{ color: "rgba(139,92,246,0.7)", fontSize: "18px" }}>
            megribi.vercel.app
          </span>
        </div>
      </div>
    ),
    { ...size },
  );
}
