// frontend/src/lib/api/proxyBackend.ts
//
// Next の /api/* から Flask バックエンドへの透過プロキシ（GET）の共通実装。
//
// 10 本の route.ts が「BACKEND_URL → fetch(next.revalidate) → arrayBuffer →
// content-type 転記 → ok のときだけ cache-control 付与 → 例外は 502」という同じ本文を
// 各 33〜57 行で持っていたので、ここへ集約した。ルートごとの違いは
//   (a) レート制限の有無と上限 (b) クエリの組み立て方 (c) content-type の既定値
// の3つだけなので、それを引数として並べて1画面で見えるようにしてある。
//
// 挙動は集約前と同一。契約は src/app/api/proxyRoutes.test.ts が10本分固定している。
import { NextRequest, NextResponse } from "next/server";

import { getBackendBaseUrl } from "@/lib/backendUrl";
import { rateLimit, rateLimitHeaders } from "@/lib/rateLimit/apiRateLimit";

export type ProxyBackendOptions = {
  /** バックエンド側のパス（先頭スラッシュ込み。例: "/api/range"） */
  path: string;
  /** CDN キャッシュ秒。fetch の revalidate と s-maxage を兼ねる */
  ttlSeconds: number;
  /** cache-control の stale-while-revalidate 秒 */
  swrSeconds: number;
  /** レート制限。省略＝制限なし。limit 省略時は API_RATE_LIMIT_PER_MINUTE の既定値 */
  rateLimit?: { key: string; limit?: number };
  /**
   * クエリ文字列（先頭の "?" は付けない）を組み立てる。省略＝クエリ無し。
   * 空文字を返した場合は "?" ごと付かない。
   */
  buildQuery?: (searchParams: URLSearchParams) => string;
  /** バックエンドが content-type を返さなかったときに補う値 */
  defaultContentType?: string;
};

/** `store` パラメータの解決（未指定・空白のみなら既定店舗）。3ルートで共通。 */
export function resolveStoreParam(searchParams: URLSearchParams, defaultStore: string): string {
  const raw = searchParams.get("store");
  return (raw && raw.trim()) || defaultStore;
}

export async function proxyBackendGet(
  req: NextRequest,
  opts: ProxyBackendOptions,
): Promise<NextResponse> {
  if (opts.rateLimit) {
    const rl = await rateLimit(req, opts.rateLimit.key, opts.rateLimit.limit);
    if (!rl.success) {
      return new NextResponse("Too Many Requests", {
        status: 429,
        headers: rateLimitHeaders(rl),
      });
    }
  }

  const base = getBackendBaseUrl();
  const query = opts.buildQuery ? opts.buildQuery(req.nextUrl.searchParams) : "";
  const targetUrl = query ? `${base}${opts.path}?${query}` : `${base}${opts.path}`;

  try {
    const backendRes = await fetch(targetUrl, { next: { revalidate: opts.ttlSeconds } });
    const buf = await backendRes.arrayBuffer();

    const headers = new Headers();
    const contentType = backendRes.headers.get("content-type");
    if (contentType) {
      headers.set("content-type", contentType);
    } else if (opts.defaultContentType) {
      headers.set("content-type", opts.defaultContentType);
    }
    // エラー応答をCDNに焼き付けないため、cache-control は ok のときだけ付ける。
    if (backendRes.ok) {
      headers.set(
        "cache-control",
        `public, s-maxage=${opts.ttlSeconds}, stale-while-revalidate=${opts.swrSeconds}`,
      );
    }

    return new NextResponse(buf, {
      status: backendRes.status,
      statusText: backendRes.statusText,
      headers,
    });
  } catch (err) {
    const detail = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ ok: false, error: "proxy-error", detail }, { status: 502 });
  }
}
