import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { isProductionHostname, shouldEnableAnalytics } from "./analytics";

// ────────────────────────────────────────────────────────────────────────────
// 純粋関数（window / 測定 ID 非依存）— GA を発火してよいかの判定ロジックの網羅テスト。
// 「hostname≠本番」または「開発者オプトアウト」または「測定 ID なし」の時は必ず無効になる。
// ────────────────────────────────────────────────────────────────────────────

describe("isProductionHostname", () => {
  it("returns true only for the two production hostnames", () => {
    expect(isProductionHostname("meguribi.jp")).toBe(true);
    expect(isProductionHostname("www.meguribi.jp")).toBe(true);
  });

  it("returns false for localhost / preview / dev / look-alike hosts", () => {
    for (const host of [
      "localhost",
      "127.0.0.1",
      "megribi-monitor-git-main.vercel.app",
      "megribi.vercel.app",
      "staging.meguribi.jp", // サブドメインは本番ではない
      "meguribi.jp.evil.com", // 前方一致攻撃を弾く
      "notmeguribi.jp",
      "",
    ]) {
      expect(isProductionHostname(host)).toBe(false);
    }
  });
});

describe("shouldEnableAnalytics (guard predicate)", () => {
  const base = { measurementId: "G-TEST123", hostname: "meguribi.jp", devOptedOut: false };

  it("enables only when id present AND production host AND not opted out", () => {
    expect(shouldEnableAnalytics(base)).toBe(true);
    expect(shouldEnableAnalytics({ ...base, hostname: "www.meguribi.jp" })).toBe(true);
  });

  it("is disabled when the measurement id is missing", () => {
    expect(shouldEnableAnalytics({ ...base, measurementId: "" })).toBe(false);
  });

  it("is disabled on non-production hosts even with a valid id", () => {
    expect(shouldEnableAnalytics({ ...base, hostname: "localhost" })).toBe(false);
    expect(shouldEnableAnalytics({ ...base, hostname: "megribi.vercel.app" })).toBe(false);
  });

  it("is disabled when the developer opt-out flag is set, even on production", () => {
    expect(shouldEnableAnalytics({ ...base, devOptedOut: true })).toBe(false);
  });
});

// ────────────────────────────────────────────────────────────────────────────
// ランタイム経路（fake window + 測定 ID あり）— track()/オプトアウト/ga-disable の実挙動。
// GA_MEASUREMENT_ID はモジュール読込時に確定するため、環境変数を差し替えて動的 import する。
// ────────────────────────────────────────────────────────────────────────────

const TEST_ID = "G-TEST00E2E0";

type FakeStorage = {
  getItem: (k: string) => string | null;
  setItem: (k: string, v: string) => void;
  removeItem: (k: string) => void;
};

function makeFakeStorage(seed: Record<string, string> = {}): FakeStorage {
  const store = new Map<string, string>(Object.entries(seed));
  return {
    getItem: (k) => (store.has(k) ? (store.get(k) as string) : null),
    setItem: (k, v) => void store.set(k, v),
    removeItem: (k) => void store.delete(k),
  };
}

function installWindow(opts: {
  hostname: string;
  storageSeed?: Record<string, string>;
}): { gtagSpy: ReturnType<typeof vi.fn>; storage: FakeStorage; win: Record<string, unknown> } {
  const gtagSpy = vi.fn();
  const storage = makeFakeStorage(opts.storageSeed);
  const win: Record<string, unknown> = {
    location: { hostname: opts.hostname },
    localStorage: storage,
    gtag: gtagSpy,
  };
  (globalThis as { window?: unknown }).window = win;
  return { gtagSpy, storage, win };
}

async function loadModule() {
  vi.resetModules();
  vi.stubEnv("NEXT_PUBLIC_GA_MEASUREMENT_ID", TEST_ID);
  return import("./analytics");
}

describe("runtime guard: track() / opt-out / ga-disable", () => {
  let infoSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    infoSpy = vi.spyOn(console, "info").mockImplementation(() => {});
  });

  afterEach(() => {
    infoSpy.mockRestore();
    vi.unstubAllEnvs();
    delete (globalThis as { window?: unknown }).window;
  });

  it("track() fires gtag on production host (not opted out)", async () => {
    const { gtagSpy } = installWindow({ hostname: "meguribi.jp" });
    const mod = await loadModule();
    mod.track("range_mode_change", { mode: "yesterday" });
    expect(gtagSpy).toHaveBeenCalledWith("event", "range_mode_change", { mode: "yesterday" });
  });

  it("track() is a no-op on a non-production host (even with a valid id)", async () => {
    const { gtagSpy } = installWindow({ hostname: "localhost" });
    const mod = await loadModule();
    mod.track("compare_add_store", { slug: "shibuya" });
    expect(gtagSpy).not.toHaveBeenCalled();
  });

  it("track() is a no-op when the device is dev-opted-out on production", async () => {
    const { gtagSpy } = installWindow({
      hostname: "meguribi.jp",
      storageSeed: { "meguribi:ga-dev-optout": "1" },
    });
    const mod = await loadModule();
    expect(mod.isDevOptedOut()).toBe(true);
    mod.track("favorite_add", { slug: "ebisu" });
    expect(gtagSpy).not.toHaveBeenCalled();
  });

  it("?dev=1 persists the opt-out flag and arms window['ga-disable-<ID>'] before any beacon", async () => {
    const { storage, win } = installWindow({ hostname: "meguribi.jp" });
    const mod = await loadModule();
    const optedOut = mod.syncDevOptOutFromQuery(new URLSearchParams("dev=1"));
    expect(optedOut).toBe(true);
    expect(storage.getItem("meguribi:ga-dev-optout")).toBe("1");
    expect(win[`ga-disable-${TEST_ID}`]).toBe(true);
    expect(mod.analyticsEnabled()).toBe(false);
  });

  it("?dev=0 clears the opt-out flag and re-enables ga-disable on production", async () => {
    const { storage, win } = installWindow({
      hostname: "meguribi.jp",
      storageSeed: { "meguribi:ga-dev-optout": "1" },
    });
    const mod = await loadModule();
    const optedOut = mod.syncDevOptOutFromQuery(new URLSearchParams("dev=0"));
    expect(optedOut).toBe(false);
    expect(storage.getItem("meguribi:ga-dev-optout")).toBeNull();
    expect(win[`ga-disable-${TEST_ID}`]).toBe(false);
    expect(mod.analyticsEnabled()).toBe(true);
  });
});
