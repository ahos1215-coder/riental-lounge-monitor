import { NextRequest, NextResponse } from "next/server";
import { rateLimit, rateLimitHeaders } from "@/lib/rateLimit/apiRateLimit";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:5000";

/** 実測データは5分おきに更新 → 60秒CDNキャッシュ、300秒stale-while-revalidate */
const CACHE_HEADER = "public, s-maxage=60, stale-while-revalidate=300";

export async function GET(req: NextRequest) {
  const rl = await rateLimit(req, "range_multi", 30);
  if (!rl.success) return new NextResponse("Too Many Requests", { status: 429, headers: rateLimitHeaders(rl) });
  const base = BACKEND_URL.replace(/\/+$/, "");
  const search = req.nextUrl.searchParams.toString();
  const targetUrl = search
    ? `${base}/api/range_multi?${search}`
    : `${base}/api/range_multi`;

  try {
    const backendRes = await fetch(targetUrl, { next: { revalidate: 60 } });
    const buf = await backendRes.arrayBuffer();

    const headers = new Headers();
    const contentType = backendRes.headers.get("content-type");
    if (contentType) headers.set("content-type", contentType);
    if (backendRes.ok) headers.set("cache-control", CACHE_HEADER);

    return new NextResponse(buf, {
      status: backendRes.status,
      statusText: backendRes.statusText,
      headers,
    });
  } catch (err) {
    const detail = err instanceof Error ? err.message : String(err);
    return NextResponse.json(
      { ok: false, error: "proxy-error", detail },
      { status: 502 },
    );
  }
}
