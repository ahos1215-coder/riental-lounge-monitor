import { ImageResponse } from "next/og";

export const runtime = "edge";

export const alt = "めぐりび MEGRIBI — オリエンタルラウンジの混雑マップ";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OpenGraphImage() {
  return new ImageResponse(
    (
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
          混雑・男女比・予測で、今夜の一軒を選びやすく
        </div>
      </div>
    ),
    { ...size },
  );
}
