import { NextRequest, NextResponse } from "next/server";
import { proxyBackendGet } from "@/lib/api/proxyBackend";

/** 2軒目情報はほぼ静的（手動更新のみ）→ 1時間CDNキャッシュ、2時間stale-while-revalidate */
const TTL_SECONDS = 3600;

export async function GET(req: NextRequest): Promise<NextResponse> {
  return proxyBackendGet(req, {
    path: "/api/second_venues",
    ttlSeconds: TTL_SECONDS,
    swrSeconds: 7200,
    buildQuery: (sp) => `store=${encodeURIComponent(sp.get("store") ?? "")}`,
    defaultContentType: "application/json",
  });
}
