import { ImageResponse } from "next/og";
import { getStoreMetaBySlugStrict } from "@/app/config/stores";

export const runtime = "edge";

export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

type Props = {
  params: Promise<{ id: string }>;
};

export default async function StoreOGImage({ params }: Props) {
  const { id } = await params;
  const store = getStoreMetaBySlugStrict(id);
  const label = store ? store.label : id;
  const areaLabel = store ? store.areaLabel : "";

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
              "radial-gradient(ellipse 80% 60% at 80% 20%, rgba(99,102,241,0.12) 0%, transparent 70%)",
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
                background: "rgba(16,185,129,0.15)",
                border: "1px solid rgba(16,185,129,0.3)",
                color: "#6ee7b7",
                fontSize: "16px",
                padding: "4px 16px",
                borderRadius: "100px",
              }}
            >
              リアルタイム混雑情報
            </span>
          </div>

          <div
            style={{
              color: "white",
              fontSize: "64px",
              fontWeight: 700,
              lineHeight: 1.1,
              letterSpacing: "-0.02em",
            }}
          >
            オリエンタルラウンジ
          </div>
          <div
            style={{
              color: "white",
              fontSize: "72px",
              fontWeight: 700,
              lineHeight: 1.1,
              letterSpacing: "-0.02em",
              marginTop: "8px",
            }}
          >
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
            alignItems: "center",
          }}
        >
          <span style={{ color: "rgba(255,255,255,0.3)", fontSize: "18px" }}>
            混雑傾向・男女比・ML 予測をまとめてチェック
          </span>
          <span style={{ color: "rgba(99,102,241,0.7)", fontSize: "18px" }}>
            megribi.vercel.app
          </span>
        </div>
      </div>
    ),
    { ...size },
  );
}
