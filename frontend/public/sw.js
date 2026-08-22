// Service Worker for めぐりび (MEGRIBI)
// Strategy: 許可リストに載っている静的アセットのみ cache-first(stale-while-revalidate)。
// それ以外の同一オリジンGET（HTMLナビゲーション・RSC payload・不明な動的リクエスト）は
// SW を経由させず素通しする（network-only）。

// ===== 判定ロジック（純関数） =====
// self/caches など Service Worker 専用のグローバルに一切依存しない。
// 2026-08-22 総合レビュー対応（検証記録は memory/general-review-2026-08-22.md）:
// 以前は「/api/ と別オリジン以外の全GET」をキャッシュ候補にしており、RSC payload・
// 動的HTML・404/500レスポンスまで拾い得た。5分毎に変わる混雑データを扱うサイトで
// 「前回訪問時の表示のまま」が起きる実害があったため、許可リスト方式に反転する。
// この判定部分だけを純関数として切り出すことで、Vitest（node環境）からも
// self/caches をモックせずにそのまま固定テストできる（下の module.exports 参照）。

const CACHEABLE_STATIC_PATTERNS = [
  /^\/_next\/static\//, // Next.js のビルド成果物（JS/CSS等）。ファイル名に content hash が入る fingerprint 資産
  /\.(?:woff2?|ttf|otf|eot)$/i, // 自前配置フォント
  /^\/favicon\.ico$/, // src/app/favicon.ico（Next App Router の規約で /favicon.ico に配信される）
  /^\/icons\//, // public/icons/ 配下のPWAアイコン
];

/** 許可リストに載っている静的アセットへのリクエストかどうか。 */
function isCacheableStaticAssetPath(pathname) {
  return CACHEABLE_STATIC_PATTERNS.some((pattern) => pattern.test(pathname));
}

/**
 * Next.js のクライアント側ルーティングが投げる RSC payload 取得リクエストかどうか。
 * これは `mode: "navigate"` にならない同一オリジンGETとして飛んでくるため、
 * 何もしなければ下の許可リスト判定に落ちて「不明な動的リクエスト」として素通しされるが、
 * 判定意図を明示するために独立した関数にしておく（HTMLナビゲーションと同じく
 * 常に最新を取りに行くべきもので、キャッシュ対象にしてはいけない）。
 */
function isRscOrDynamicRequest(url, headers) {
  if (url.searchParams.has("_rsc")) return true;
  const accept = headers && typeof headers.get === "function" ? headers.get("accept") : null;
  if (accept && accept.includes("text/x-component")) return true;
  return false;
}

// Node/Vitest から `require("public/sw.js")` されたときだけ到達する分岐
// （実際の Service Worker 実行環境に `module` は存在しない）。
if (typeof module !== "undefined" && module.exports) {
  module.exports = { isCacheableStaticAssetPath, isRscOrDynamicRequest };
}

// ===== ここから下は Service Worker 実行環境専用 =====
if (typeof self !== "undefined" && typeof self.addEventListener === "function") {
  // キャッシュ名にデプロイのバージョンを含める。
  // public/ 配下はビルドパイプラインを通らない静的ファイルなのでこのファイル自体は
  // デプロイ間で変化しないが、layout.tsx が
  // `register("/sw.js?v=<commit-sha-or-build-id>")` のようにクエリ付きURLで登録するため
  // (frontend/src/app/layout.tsx の SW_VERSION 参照)、ブラウザはデプロイごとに
  // 新しい登録URLとして SW を再インストールする。ここで self.location.search から
  // そのバージョンを読み取って CACHE_NAME に含めることで、旧デプロイのキャッシュ名と
  // 一致しなくなり、activate ハンドラの「CACHE_NAME 以外を削除」が確実に効くようになる。
  // クエリが無い（ローカル開発などで直接 /sw.js を登録した）場合は固定名にフォールバックする。
  const SW_VERSION = new URL(self.location.href).searchParams.get("v") || "dev";
  const CACHE_NAME = `megribi-v2-${SW_VERSION}`;
  const STATIC_ASSETS = ["/", "/stores", "/reports", "/mypage"];

  self.addEventListener("install", (event) => {
    event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS)));
    self.skipWaiting();
  });

  self.addEventListener("activate", (event) => {
    event.waitUntil(
      caches.keys().then((keys) =>
        Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))),
      ),
    );
    self.clients.claim();
  });

  self.addEventListener("fetch", (event) => {
    const url = new URL(event.request.url);

    // Skip non-GET requests
    if (event.request.method !== "GET") return;

    // Skip API calls and external requests — always go to network
    if (url.pathname.startsWith("/api/") || url.origin !== self.location.origin) {
      return;
    }

    // HTMLナビゲーションはキャッシュに書き込まない（=常に最新を取りに行く）。
    // オフライン時のみ、install時にprecacheした内容（無ければ "/"）へ読み取りフォールバックする
    // （この読み取りフォールバック自体は元からある挙動を維持。書き込みだけをやめた）。
    if (event.request.mode === "navigate") {
      event.respondWith(
        fetch(event.request).catch(() =>
          caches.match(event.request).then((r) => r || caches.match("/")),
        ),
      );
      return;
    }

    // RSC payload 等、常に最新であるべき動的フェッチは SW を経由させず素通しする
    if (isRscOrDynamicRequest(url, event.request.headers)) {
      return;
    }

    // 許可リスト外（動的HTML相当・不明な同一オリジンGETなど）も素通し。
    // ここで拾わないことが「前回訪問時の表示のまま」事故の再発防止そのもの。
    if (!isCacheableStaticAssetPath(url.pathname)) {
      return;
    }

    // 許可リストに載っている静的アセットのみ stale-while-revalidate。
    // response.ok のときだけ書き込み、書き込みの Promise は event.waitUntil に繋いで
    // respondWith が確定した後（cached を即返した場合）でも SW が早期終了しないようにする。
    event.respondWith(
      caches.match(event.request).then((cached) => {
        const fetchPromise = fetch(event.request).then((response) => {
          if (response.ok) {
            const clone = response.clone();
            event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone)));
          }
          return response;
        });
        return cached || fetchPromise;
      }),
    );
  });
}
