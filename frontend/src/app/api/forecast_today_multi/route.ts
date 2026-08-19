import { NextRequest, NextResponse } from "next/server";
import { proxyBackendGet } from "@/lib/api/proxyBackend";

/** 予測モデルは15分ごとに再計算 → 5分CDNキャッシュ、15分stale-while-revalidate（forecast_today と同じTTL） */
const TTL_SECONDS = 300;

export async function GET(req: NextRequest): Promise<NextResponse> {
  return proxyBackendGet(req, {
    path: "/api/forecast_today_multi",
    ttlSeconds: TTL_SECONDS,
    swrSeconds: 900,
    rateLimit: { key: "forecast_multi", limit: 20 },
    buildQuery: (sp) => `stores=${encodeURIComponent(sp.get("stores") ?? "")}`,
  });
}
