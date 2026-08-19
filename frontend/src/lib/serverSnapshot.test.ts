// frontend/src/lib/serverSnapshot.test.ts
//
// 番犬（D-02）: store/[id]/page.tsx にあった fetchJsonWithTimeout（5000ms・AbortController）を
// fetchBackendSnapshot に統合し、タイムアウトを引数化した。値そのものは変えていないことを固定する。
// - トップ/一覧: 2500ms（既定値のまま）
// - 店舗ページの初回スナップショット: 5000ms（呼び出し側が明示的に渡す）
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  SNAPSHOT_TIMEOUT_MS,
  STORE_SNAPSHOT_TIMEOUT_MS,
  fetchBackendSnapshot,
} from "./serverSnapshot";

vi.mock("server-only", () => ({}));

const realFetch = globalThis.fetch;

/** signal が abort されるまで解決しない fetch（タイムアウト経路の検証用）。 */
function hangingFetch(): typeof globalThis.fetch {
  return ((_url: string, init?: RequestInit) =>
    new Promise((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(new Error("aborted")));
    })) as unknown as typeof globalThis.fetch;
}

afterEach(() => {
  globalThis.fetch = realFetch;
  vi.unstubAllEnvs();
});

beforeEach(() => {
  vi.stubEnv("BACKEND_URL", "http://backend.test");
});

describe("fetchBackendSnapshot — タイムアウト値の統合", () => {
  it("既定のタイムアウトは 2500ms、店舗ページ用は 5000ms（旧 fetchJsonWithTimeout と同値）", () => {
    expect(SNAPSHOT_TIMEOUT_MS).toBe(2500);
    expect(STORE_SNAPSHOT_TIMEOUT_MS).toBe(5000);
  });

  it("渡したタイムアウトを超えたら null を返す（例外は投げない）", async () => {
    globalThis.fetch = hangingFetch();
    const started = Date.now();
    const res = await fetchBackendSnapshot<unknown>("/api/range?store=x", 120, 30);
    expect(res).toBeNull();
    expect(Date.now() - started).toBeLessThan(1500);
  });

  it("長いタイムアウト(5000ms)を渡した経路は、短時間では打ち切られない", async () => {
    globalThis.fetch = hangingFetch();
    const slow = fetchBackendSnapshot<unknown>("/api/range?store=x", 120, 5000);
    const marker = new Promise((resolve) => setTimeout(() => resolve("still-waiting"), 120));
    await expect(Promise.race([slow, marker])).resolves.toBe("still-waiting");
    // ぶら下がった Promise を後始末（未処理拒否を残さない）
    void slow.catch(() => null);
  });

  it("パスは BACKEND_URL に連結され、revalidate がそのまま渡る", async () => {
    const calls: { url: string; init?: RequestInit }[] = [];
    globalThis.fetch = ((url: string, init?: RequestInit) => {
      calls.push({ url, init });
      return Promise.resolve({ ok: true, json: async () => ({ rows: [] }) } as Response);
    }) as unknown as typeof globalThis.fetch;

    const res = await fetchBackendSnapshot<{ rows: unknown[] }>(
      "/api/forecast_today?store=shibuya",
      86_400,
      STORE_SNAPSHOT_TIMEOUT_MS,
    );
    expect(res).toEqual({ rows: [] });
    expect(calls[0].url).toBe("http://backend.test/api/forecast_today?store=shibuya");
    expect((calls[0].init as { next?: { revalidate?: number } }).next?.revalidate).toBe(86_400);
  });

  it("res.ok=false と JSON パース失敗はどちらも null（旧実装と同じフェイルセーフ）", async () => {
    globalThis.fetch = (() =>
      Promise.resolve({ ok: false, json: async () => ({}) } as Response)) as unknown as typeof globalThis.fetch;
    await expect(fetchBackendSnapshot<unknown>("/api/range", 120)).resolves.toBeNull();

    globalThis.fetch = (() =>
      Promise.resolve({
        ok: true,
        json: async () => {
          throw new Error("bad json");
        },
      } as unknown as Response)) as unknown as typeof globalThis.fetch;
    await expect(fetchBackendSnapshot<unknown>("/api/range", 120)).resolves.toBeNull();
  });
});
