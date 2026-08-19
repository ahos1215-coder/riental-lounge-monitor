import { ImageResponse } from "next/og";

import { HUB_OG_CONTENT_TYPE, HUB_OG_SIZE, hubOgImage } from "@/lib/og/hubOgImage";

export const runtime = "edge";

export const alt = "めぐりび MEGRIBI — オリエンタルラウンジの混雑マップ";
export const size = HUB_OG_SIZE;
export const contentType = HUB_OG_CONTENT_TYPE;

export default function OpenGraphImage() {
  return new ImageResponse(hubOgImage("混雑・男女比・予測で、今夜の一軒を選びやすく"), { ...size });
}
