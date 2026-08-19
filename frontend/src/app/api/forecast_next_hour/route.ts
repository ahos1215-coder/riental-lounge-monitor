import { NextRequest, NextResponse } from "next/server";
import { proxyBackendGet, resolveStoreParam } from "@/lib/api/proxyBackend";
import { DEFAULT_STORE } from "../../config/stores";

/** 予測モデルは15分ごとに再計算 → 5分CDNキャッシュ、15分stale-while-revalidate（forecast_today と同一方針） */
const TTL_SECONDS = 300;

export async function GET(req: NextRequest): Promise<NextResponse> {
  return proxyBackendGet(req, {
    path: "/api/forecast_next_hour",
    ttlSeconds: TTL_SECONDS,
    swrSeconds: 900,
    rateLimit: { key: "forecast_next_hour", limit: 30 },
    buildQuery: (sp) => `store=${encodeURIComponent(resolveStoreParam(sp, DEFAULT_STORE))}`,
  });
}
