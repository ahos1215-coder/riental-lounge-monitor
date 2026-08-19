import { ImageResponse } from "next/og";

import { HUB_OG_CONTENT_TYPE, HUB_OG_SIZE, hubOgImage } from "@/lib/og/hubOgImage";

export const runtime = "edge";

export const alt = "めぐりび MEGRIBI — ブログ";
export const size = HUB_OG_SIZE;
export const contentType = HUB_OG_CONTENT_TYPE;

export default function BlogHubOpenGraphImage() {
  return new ImageResponse(hubOgImage("相席系ラウンジ・バーの攻略と混雑傾向の読み方"), { ...size });
}
