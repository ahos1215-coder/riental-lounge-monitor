import { ImageResponse } from "next/og";

import { HUB_OG_CONTENT_TYPE, HUB_OG_SIZE, hubOgImage } from "@/lib/og/hubOgImage";

export const runtime = "edge";

export const alt = "めぐりび MEGRIBI — ML予測レポート一覧（Daily / Weekly）";
export const size = HUB_OG_SIZE;
export const contentType = HUB_OG_CONTENT_TYPE;

export default function ReportsHubOpenGraphImage() {
  return new ImageResponse(hubOgImage("全店舗のML予測レポートをDaily/Weeklyで一覧確認"), { ...size });
}
