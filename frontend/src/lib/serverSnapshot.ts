import "server-only";

/**
 * トップ(TOP5)・店舗一覧の初期表示を「空スケルトン→JS+fetch後に描画」ではなく
 * サーバー側で1回分の実データを取得し、初期HTMLに焼き込むためのヘルパー。
 *
 * COLD SAFETY:
 * - Render/Vercel の裏側バックエンドが落ちている・遅い場合でも build/SSR を
 *   絶対に落とさない。短いタイムアウトで打ち切り、失敗時は null を返すだけ。
 * - 呼び出し側は null を「サーバー snapshot なし」として扱い、従来通り
 *   クライアント側 fetch のみで描画する（今までの挙動に完全フォールバック）。
 */

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:5000";

/** ここでのサーバー fetch はどれもトップ/一覧の初期表示用。重い予測(forecast)は含めないため短めでよい。 */
const SNAPSHOT_TIMEOUT_MS = 2500;

/**
 * バックエンド (Flask) を直接叩く（Next の /api/* プロキシは経由しない）。
 * 失敗・タイムアウト・不正レスポンスはすべて null を返し、呼び出し側に例外を投げない。
 */
export async function fetchBackendSnapshot<T>(
  path: string,
  revalidateSeconds: number,
): Promise<T | null> {
  const base = BACKEND_URL.replace(/\/+$/, "");
  const url = `${base}${path}`;

  try {
    const res = await fetch(url, {
      next: { revalidate: revalidateSeconds },
      signal: AbortSignal.timeout(SNAPSHOT_TIMEOUT_MS),
    });
    if (!res.ok) return null;
    const json = (await res.json()) as T;
    return json;
  } catch {
    // タイムアウト・DNS失敗・JSON parse失敗など、理由を問わず安全側(null)に倒す。
    return null;
  }
}
