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
    // 2026-08-22 総合レビュー対応（検証記録は memory/general-review-2026-08-22.md）:
    // backend には HTTP 200 のまま本文で ok:false を返す実在経路がある（/api/second_venues の
    // 設定不備時など）。従来は backendRes.ok（=HTTPステータスのみ）しか見ていなかったため、
    // この種の「200だが失敗」応答にも s-maxage が付いて CDN に焼き付いていた。
    // 本文が小さいとき（4KB未満）だけ JSON として試しにパースして ok:false を検出する。
    // /api/range_multi の 12000 行応答のような大きい本文は成功データとみなし、
    // 常時パースするコストは払わない（毎リクエストで数千行をJSON.parseするのは無駄が大きい）。
    let cacheableOk = backendRes.ok;
    if (cacheableOk && buf.byteLength > 0 && buf.byteLength < 4096) {
      try {
        const parsed: unknown = JSON.parse(new TextDecoder().decode(buf));
        if (
          parsed !== null &&
          typeof parsed === "object" &&
          (parsed as { ok?: unknown }).ok === false
        ) {
          cacheableOk = false;
        }
      } catch {
        // JSON でない本文（例: second_venues が content-type 未設定でテキストを返すテスト経路）は
        // 判定不能として cacheableOk を書き換えず素通しする（＝従来通りキャッシュされる）。
        // 実運用でバックエンドが200で返す本文は基本JSONなので、ここに落ちるのは想定外系のみ。
      }
    }

    if (cacheableOk) {
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
