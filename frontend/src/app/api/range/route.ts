import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:5000";

export async function GET(req: NextRequest) {
  const base = BACKEND_URL.replace(/\/+$/, "");
  const search = req.nextUrl.searchParams.toString();
  const targetUrl = search ? `${base}/api/range?${search}` : `${base}/api/range`;

  try {
    const backendRes = await fetch(targetUrl, { next: { revalidate: 0 } });
    const buf = await backendRes.arrayBuffer();

    const headers = new Headers();
    const contentType = backendRes.headers.get("content-type");
    if (contentType) {
      headers.set("content-type", contentType);
    }

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
