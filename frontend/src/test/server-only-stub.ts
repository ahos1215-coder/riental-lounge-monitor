// vitest 用: Next.js の "server-only"（クライアントバンドルへの混入を防ぐマーカー）を空モジュールに差し替える。
// node 環境の vitest には実体が無く、サーバー専用モジュール（lib/serverSnapshot 等）を import する
// テストが "Cannot find package 'server-only'" で落ちるため、vitest.config.ts の alias でここを指す。
export {};
