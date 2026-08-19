import "server-only";

import { getBackendBaseUrl } from "@/lib/backendUrl";

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

/** ここでのサーバー fetch はどれもトップ/一覧の初期表示用。重い予測(forecast)は含めないため短めでよい。 */
export const SNAPSHOT_TIMEOUT_MS = 2500;

/**
 * 店舗ページ（/store/[id]）の初回スナップショット取得タイムアウト。Render 等のコールドスタート時に
 * ISR の再生成コストを一定時間で打ち切るための安全弁。超過/失敗時は null を返し、
 * StorePageClient 側は initialSnapshot 無しの通常 CSR フローにフォールバックする。
 *
 * ISR の再生成はバックグラウンドの stale-while-revalidate であり、訪問者のレスポンスを
 * ブロックしない（再生成が遅くても既存キャッシュが即返る）。一方 initialSnapshot が null に
 * なった場合の代償（クライアント側でコールドウォーターフォール全部を踏む）の方がはるかに大きい
 * ため、多少再生成が遅くなってもタイムアウトは長めに倒す（トップ/一覧の 2500ms とは別値）。
 */
export const STORE_SNAPSHOT_TIMEOUT_MS = 5000;

/**
 * バックエンド (Flask) を直接叩く（Next の /api/* プロキシは経由しない）。
 * 失敗・タイムアウト・不正レスポンスはすべて null を返し、呼び出し側に例外を投げない。
 *
 * `timeoutMs` は既定でトップ/一覧向けの 2500ms。店舗ページの初回スナップショットのように
 * 重い経路は呼び出し側が STORE_SNAPSHOT_TIMEOUT_MS を明示的に渡す。
 */
export async function fetchBackendSnapshot<T>(
  path: string,
  revalidateSeconds: number,
  timeoutMs: number = SNAPSHOT_TIMEOUT_MS,
): Promise<T | null> {
  const base = getBackendBaseUrl();
  const url = `${base}${path}`;

  try {
    const res = await fetch(url, {
      next: { revalidate: revalidateSeconds },
      signal: AbortSignal.timeout(timeoutMs),
    });
    if (!res.ok) return null;
    const json = (await res.json()) as T;
    return json;
  } catch {
    // タイムアウト・DNS失敗・JSON parse失敗など、理由を問わず安全側(null)に倒す。
    return null;
  }
}
