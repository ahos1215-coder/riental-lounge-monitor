import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:5000";

/** 2軒目情報はほぼ静的（手動更新のみ）→ 1時間CDNキャッシュ、2時間stale-while-revalidate */
const CACHE_HEADER = "public, s-maxage=3600, stale-while-revalidate=7200";

export async function GET(req: NextRequest) {
  const base = BACKEND_URL.replace(/\/+$/, "");
  const store = new URL(req.url).searchParams.get("store") ?? "";
  const targetUrl = `${base}/api/second_venues?store=${encodeURIComponent(store)}`;

  try {
    const backendRes = await fetch(targetUrl, { next: { revalidate: 3600 } });
    const buf = await backendRes.arrayBuffer();

    const headers = new Headers();
    const contentType = backendRes.headers.get("content-type");
    if (contentType) {
      headers.set("content-type", contentType);
    } else {
      headers.set("content-type", "application/json");
    }
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
      { status: 502 }
    );
  }
}
