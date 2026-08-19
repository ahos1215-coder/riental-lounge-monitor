import { NextRequest, NextResponse } from "next/server";
import { proxyBackendGet } from "@/lib/api/proxyBackend";

/** 実測データは5分おきに更新 → 240秒CDNキャッシュ、300秒stale-while-revalidate（/api/range と同一方針） */
const TTL_SECONDS = 240;

export async function GET(req: NextRequest): Promise<NextResponse> {
  return proxyBackendGet(req, {
    path: "/api/range_multi",
    ttlSeconds: TTL_SECONDS,
    swrSeconds: 300,
    rateLimit: { key: "range_multi", limit: 30 },
    buildQuery: (sp) => sp.toString(),
  });
}
