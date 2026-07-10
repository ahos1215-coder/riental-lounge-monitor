import { ImageResponse } from "next/og";
import { getStoreMetaBySlugStrict } from "@/app/config/stores";

export const runtime = "edge";

export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

/**
 * その瞬間が属する「週」を JST（Asia/Tokyo）基準の月曜始まりで求め、`YYYY年M月D日週` を返す。
 *
 * 従来は `new Date()` の getDay/getDate（サーバーの実行環境=UTC 基準）で月曜を算出していたため、
 * 毎週月曜 00:00〜08:59 JST（= 日曜 15:00〜23:59 UTC）の約9時間だけ前週の日付を表示していた。
 * ここでは Intl で JST の壁時計（年月日・曜日）を取り出してから月曜へ巻き戻すことで、
 * 日次側（timeZone: "Asia/Tokyo"）と表示基準を一致させる。純関数のためユニットテスト可能。
 */
export function jstWeekLabel(now: Date = new Date()): string {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Tokyo",
    year: "numeric",
    month: "numeric",
    day: "numeric",
    weekday: "short",
  }).formatToParts(now);
  const pick = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  const year = Number(pick("year"));
  const month = Number(pick("month"));
  const day = Number(pick("day"));
  const weekdayIndex: Record<string, number> = {
    Sun: 0,
    Mon: 1,
    Tue: 2,
    Wed: 3,
    Thu: 4,
    Fri: 5,
    Sat: 6,
  };
  const dow = weekdayIndex[pick("weekday")] ?? 0;
  // JST の壁時計を UTC 上に写像し、そのまま UTC 系の日付演算で月曜へ巻き戻す（TZ 二重変換を避ける）。
  const monday = new Date(Date.UTC(year, month - 1, day));
  monday.setUTCDate(monday.getUTCDate() - ((dow + 6) % 7));
  return `${monday.getUTCFullYear()}年${monday.getUTCMonth() + 1}月${monday.getUTCDate()}日週`;
}

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
              ML 予測 Weekly Report
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
            meguribi.jp
          </span>
        </div>
      </div>
    ),
    { ...size },
  );
}
