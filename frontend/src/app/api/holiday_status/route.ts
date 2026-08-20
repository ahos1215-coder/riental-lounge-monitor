import { NextRequest, NextResponse } from "next/server";
import { proxyBackendGet } from "@/lib/api/proxyBackend";

/** 連休判定は日付単位で固定なので 1 時間程度キャッシュして十分 */
const TTL_SECONDS = 3600;

export async function GET(req: NextRequest): Promise<NextResponse> {
  return proxyBackendGet(req, {
    path: "/api/holiday_status",
    ttlSeconds: TTL_SECONDS,
    rateLimit: { key: "holiday_status", limit: 60 },
    swrSeconds: 7200,
    // date 未指定ならクエリごと付けない（バックエンド側で「今日」扱い）
    buildQuery: (sp) => {
      const date = sp.get("date");
      return date ? `date=${encodeURIComponent(date)}` : "";
    },
  });
}
