// frontend/src/lib/backendUrl.ts
//
// Flask バックエンドのベース URL の単一ソース。
//
// 以前は `process.env.BACKEND_URL ?? "http://localhost:5000"` が 12 箇所、
// `BACKEND-URL` 別名の保険付き＋既定値 127.0.0.1 が 2 箇所に手書きされており、
// 「どの経路から呼んだか」で既定値と別名の保険の有無が変わっていた。ここに一本化する。
//
// 本番（Vercel）では BACKEND_URL が必須設定なので、既定値はローカル開発でしか使われない。

/** ローカル開発でのみ使われる既定値（本番は BACKEND_URL 必須。plan/ENV.md 参照）。 */
const DEFAULT_BACKEND_URL = "http://localhost:5000";

/** Vercel 側で `BACKEND-URL` として登録されてしまうケースがあるため、別名も許容する。 */
function backendUrlFromEnv(): string | undefined {
  return process.env.BACKEND_URL ?? process.env["BACKEND-URL"];
}

/**
 * 環境変数でバックエンド URL が明示指定されているか。
 * false＝既定値（ローカル開発）で動いている、の意味。開発時の診断ログ用。
 */
export function isBackendUrlFromEnv(): boolean {
  return backendUrlFromEnv() !== undefined;
}

/** バックエンドのベース URL。末尾スラッシュは除去済みなので `${base}/api/...` で連結してよい。 */
export function getBackendBaseUrl(): string {
  return (backendUrlFromEnv() ?? DEFAULT_BACKEND_URL).replace(/\/+$/, "");
}
