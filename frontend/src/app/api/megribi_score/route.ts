import { NextRequest, NextResponse } from "next/server";
import { proxyBackendGet } from "@/lib/api/proxyBackend";

/** スコアは実測データ(5分毎更新)から算出 → 180秒CDNキャッシュ、600秒stale-while-revalidate */
const TTL_SECONDS = 180;

export async function GET(req: NextRequest): Promise<NextResponse> {
  return proxyBackendGet(req, {
    path: "/api/megribi_score",
    ttlSeconds: TTL_SECONDS,
    swrSeconds: 600,
    rateLimit: { key: "megribi_score", limit: 30 },
    buildQuery: (sp) => sp.toString(),
  });
}
