import { NextRequest, NextResponse } from "next/server";
import { proxyBackendGet } from "@/lib/api/proxyBackend";

/** 実測データは5分おきに更新 → 240秒CDNキャッシュ、300秒stale-while-revalidate */
const TTL_SECONDS = 240;

export async function GET(req: NextRequest): Promise<NextResponse> {
  return proxyBackendGet(req, {
    path: "/api/range",
    ttlSeconds: TTL_SECONDS,
    swrSeconds: 300,
    rateLimit: { key: "range" },
    buildQuery: (sp) => sp.toString(),
  });
}
