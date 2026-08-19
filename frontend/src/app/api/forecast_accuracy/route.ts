import { NextRequest, NextResponse } from "next/server";
import { proxyBackendGet } from "@/lib/api/proxyBackend";

/** メトリクスは学習後にしか変わらないので長めにキャッシュ */
const TTL_SECONDS = 3600;

export async function GET(req: NextRequest): Promise<NextResponse> {
  return proxyBackendGet(req, {
    path: "/api/forecast_accuracy",
    ttlSeconds: TTL_SECONDS,
    swrSeconds: 7200,
  });
}
