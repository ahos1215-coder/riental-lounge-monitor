// Service Worker for めぐりび (MEGRIBI)
// Strategy: Network-first for API, Cache-first for static assets

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
const CACHE_NAME = `megribi-v1-${SW_VERSION}`;
const STATIC_ASSETS = ["/", "/stores", "/reports", "/mypage"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key !== CACHE_NAME)
          .map((key) => caches.delete(key))
      )
    )
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

  // For navigation requests: network-first with offline fallback
  if (event.request.mode === "navigate") {
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
          return response;
        })
        .catch(() => caches.match(event.request).then((r) => r || caches.match("/")))
    );
    return;
  }

  // For static assets: stale-while-revalidate
  event.respondWith(
    caches.match(event.request).then((cached) => {
      const fetchPromise = fetch(event.request).then((response) => {
        const clone = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
        return response;
      });
      return cached || fetchPromise;
    })
  );
});
