import { NextRequest, NextResponse } from "next/server";
import { proxyBackendGet } from "@/lib/api/proxyBackend";

/**
 * 学習メトリクスは学習後にしか変わらないので長めにキャッシュする。ただし毎朝の答え合わせ（live）も
 * 載るので、Next のデータキャッシュには載せず CDN だけで持つ（proxyBackend の bypassDataCache 参照）。
 */
const TTL_SECONDS = 3600;

export async function GET(req: NextRequest): Promise<NextResponse> {
  return proxyBackendGet(req, {
    path: "/api/forecast_accuracy",
    ttlSeconds: TTL_SECONDS,
    rateLimit: { key: "forecast_accuracy", limit: 30 },
    swrSeconds: 7200,
    bypassDataCache: true,
  });
}
