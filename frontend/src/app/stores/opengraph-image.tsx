import { ImageResponse } from "next/og";

import { HUB_OG_CONTENT_TYPE, HUB_OG_SIZE, hubOgImage } from "@/lib/og/hubOgImage";

export const runtime = "edge";

export const alt = "めぐりび MEGRIBI — 店舗一覧・リアルタイム混雑比較";
export const size = HUB_OG_SIZE;
export const contentType = HUB_OG_CONTENT_TYPE;

export default function StoresHubOpenGraphImage() {
  return new ImageResponse(hubOgImage("全店舗のリアルタイム混雑・男女比を一覧で比較"), { ...size });
}
