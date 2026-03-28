import { NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:5000";

/** メトリクスは学習後にしか変わらないので長めにキャッシュ */
const CACHE_HEADER = "public, s-maxage=3600, stale-while-revalidate=7200";

export async function GET() {
  const base = BACKEND_URL.replace(/\/+$/, "");
  const apiUrl = `${base}/api/forecast_accuracy`;

  try {
    const backendRes = await fetch(apiUrl, { next: { revalidate: 3600 } });
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
