import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { getStoreMetaBySlugStrict } from "@/app/config/stores";
import {
  fetchLatestPublishedReportByStoreWithStatus,
  fetchPublishedEditorialBySlug,
} from "@/lib/supabase/blogDrafts";

/**
 * /blog/[slug], /reports/daily/[store_slug], /reports/weekly/[store_slug] は
 * ルートの app/loading.tsx が Suspense 境界を作るため、ページ側で notFound() を
 * 呼んでも Next.js がレスポンスを既にストリーミング開始しており HTTP ステータスを
 * 200 のまま返してしまう（soft-404）。
 * https://nextjs.org/docs/app/api-reference/file-conventions/loading#status-codes
 * 「ストリーミング開始前にレスポンスヘッダーが確定するため、ステータスコードは
 * ストリーミング開始後に変更できない」という Next.js の既知の制約（v15.2+ で導入された
 * streaming metadata 由来。vercel/next.js#59521 / #77235 も参照）。
 *
 * そのため、レンダリング前の proxy (旧 middleware, Next.js 16 で Node.js ランタイムが
 * デフォルト) 段階で存在確認を行い、存在しない slug はどのルートにもマッチしない内部
 * パスへ rewrite することで、Next.js 標準の（正しく 404 ステータスを返す）
 * not-found ハンドリングに委ねる。
 */

// frontend/content/blog/*.mdx のファイルシステム記事一覧
// （proxy はリクエストごとに fs を読むより静的リストの方が高速なため、ここで維持する。
//  新規 .mdx を追加した場合はここにも追記すること）
const FILESYSTEM_BLOG_SLUGS = new Set([
  "beginner-complete-guide",
  "conversation-tips-men",
  "how-to-use-prediction",
  "manager-interview",
  "prediction-how-it-works",
]);

async function blogSlugExists(slug: string): Promise<boolean> {
  const normalized = slug.trim().toLowerCase();
  if (!normalized) return false;
  if (FILESYSTEM_BLOG_SLUGS.has(normalized)) return true;
  const row = await fetchPublishedEditorialBySlug(normalized);
  return row !== null;
}

/**
 * レポートの存在確認。**取得できなかったときは「ある」側に倒す（fail-open）**。
 *
 * 2026-09-09（Supabase 402 で全リクエストが失敗した事故）:
 * 旧実装は「行が無い」と「見に行けていない」をどちらも false に潰していたため、障害中は
 * 実在する 84 本のレポート URL がすべて /__not_found__ へ rewrite され、本物の 404 として
 * CDN に載った。404 は HIT で配られるので復旧後もしばらく残り、Search Console にも
 * クロールエラーが積み上がる。取得できていないだけならページ側に通し、ページが
 * 「一時的に取得できません」を 200 で返す（ReportTemporarilyUnavailable）。
 *
 * ただし fail-open の対象は**店舗マスタに実在する slug だけ**に限る。
 * 理由: ページ側の notFound() は上のコメントのとおり soft-404（HTTP 200）になり、
 * app/not-found.tsx が無いので layout.tsx の robots{index:true} をそのまま継承する。
 * つまり slug を選ばず fail-open すると、障害中は /reports/daily/<任意文字列> が
 * 「インデックス可能な 200」で無限に返る（クロールバジェットの浪費・ゴミ URL の登録）。
 * マスタ照合は stores.json を読むだけで Supabase を引かないので、障害中でも必ず判定でき、
 * 実在 84 本を救う利益（fail-open）はそのまま残る。
 */
async function reportExists(storeSlug: string, contentType: "daily" | "weekly"): Promise<boolean> {
  const normalized = storeSlug.trim().toLowerCase();
  if (!normalized) return false;
  // マスタに無い slug はページ側も必ず notFound() を返す（reports/{daily,weekly}/[store_slug]/
  // page.tsx の getStoreMetaBySlugStrict）ので、ここで 404 に倒しても正常時の挙動は変わらない。
  if (!getStoreMetaBySlugStrict(normalized)) return false;
  const { row, failed } = await fetchLatestPublishedReportByStoreWithStatus(
    normalized,
    contentType,
  );
  if (failed) return true;
  return row !== null;
}

function notFoundRewrite(request: NextRequest) {
  return NextResponse.rewrite(new URL("/__not_found__", request.url));
}

/**
 * 閉店して店舗マスタから削除済みの店舗 slug。
 * 診断②(2026-08-20)の GSC 実測で、閉店済み /store/ay_niigata が Google に残り続け
 * （90日で193表示・21クリック・順位6.5位）、検索から来た実利用者が 404 に着地し続けて
 * いたことが判明した。404（一時的な不在）ではなく 410 Gone（恒久的な削除）を返すことで
 * Google のインデックスから早く消し、利用者には店舗一覧への案内を出す。
 * 店舗を閉店処理（stores.json から削除）したらここに slug を追記すること。
 */
const CLOSED_STORE_SLUGS = new Set(["ay_niigata", "sapporo_ag"]);

function closedStoreGone(): NextResponse {
  const html = `<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex"><title>閉店した店舗 | めぐりび</title></head>
<body style="margin:0;display:flex;min-height:100vh;align-items:center;justify-content:center;background:#050505;color:#e2e8f0;font-family:sans-serif;text-align:center">
<div><p style="font-size:15px;line-height:1.8">この店舗は閉店したため、ページを終了しました。</p>
<p style="margin-top:16px"><a href="/stores" style="color:#a5b4fc">全店舗の混雑状況一覧へ →</a></p></div>
</body></html>`;
  return new NextResponse(html, {
    status: 410,
    headers: { "content-type": "text/html; charset=utf-8" },
  });
}

export async function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;

  const storeMatch = pathname.match(/^\/store\/([^/]+)\/?$/);
  if (storeMatch && CLOSED_STORE_SLUGS.has(decodeURIComponent(storeMatch[1]).toLowerCase())) {
    return closedStoreGone();
  }

  const blogMatch = pathname.match(/^\/blog\/([^/]+)\/?$/);
  if (blogMatch) {
    const exists = await blogSlugExists(decodeURIComponent(blogMatch[1]));
    return exists ? NextResponse.next() : notFoundRewrite(request);
  }

  const dailyMatch = pathname.match(/^\/reports\/daily\/([^/]+)\/?$/);
  if (dailyMatch) {
    const exists = await reportExists(decodeURIComponent(dailyMatch[1]), "daily");
    return exists ? NextResponse.next() : notFoundRewrite(request);
  }

  const weeklyMatch = pathname.match(/^\/reports\/weekly\/([^/]+)\/?$/);
  if (weeklyMatch) {
    const exists = await reportExists(decodeURIComponent(weeklyMatch[1]), "weekly");
    return exists ? NextResponse.next() : notFoundRewrite(request);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/blog/:slug*", "/reports/daily/:slug*", "/reports/weekly/:slug*", "/store/:slug*"],
};
