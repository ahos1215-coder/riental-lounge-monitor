import { NextRequest, NextResponse } from "next/server";
import { proxyBackendGet, resolveStoreParam } from "@/lib/api/proxyBackend";
import { DEFAULT_STORE } from "../../config/stores";

/**
 * 完了済みの夜（過去日）に配信されていた予測のスナップショット。/api/forecast_today
 * と違い、対象の夜が終わればもう内容は変わらない（scripts/snapshot_forecasts.py が
 * その夜の開始前に一度だけ書き込む）ので、長め＆不変寄りの CDN キャッシュにする。
 */
const TTL_SECONDS = 86400;

export async function GET(req: NextRequest): Promise<NextResponse> {
  return proxyBackendGet(req, {
    path: "/api/forecast_snapshot",
    ttlSeconds: TTL_SECONDS,
    swrSeconds: 604800,
    rateLimit: { key: "forecast_snapshot", limit: 30 },
    buildQuery: (sp) => {
      const store = encodeURIComponent(resolveStoreParam(sp, DEFAULT_STORE));
      const date = encodeURIComponent((sp.get("date") ?? "").trim());
      return `store=${store}&date=${date}`;
    },
  });
}
