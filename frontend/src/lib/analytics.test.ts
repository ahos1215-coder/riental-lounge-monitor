import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ANALYTICS_EVENT_NAMES, isProductionHostname, shouldEnableAnalytics } from "./analytics";
import type { AnalyticsEventName } from "./analytics";
import { shouldSendPageView } from "@/components/GoogleAnalytics";
import { shouldFireExposure } from "@/app/hooks/useExposureOnce";

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
    mod.track("range_mode_change", { store_slug: "shibuya", mode: "yesterday" });
    expect(gtagSpy).toHaveBeenCalledWith("event", "range_mode_change", {
      store_slug: "shibuya",
      mode: "yesterday",
    });
  });

  it("track() is a no-op on a non-production host (even with a valid id)", async () => {
    const { gtagSpy } = installWindow({ hostname: "localhost" });
    const mod = await loadModule();
    // 2026-08-26 計測レビューR2対応: 型を index signature からイベント別型へ移行したため、
    // 旧キー `{ slug }` はもう型チェックを通らない（レビュー2-2で指摘された穴）。
    // ここは現行の必須パラメータ `store_slug` で呼ぶ。
    mod.track("compare_add_store", { store_slug: "shibuya" });
    expect(gtagSpy).not.toHaveBeenCalled();
  });

  it("track() is a no-op when the device is dev-opted-out on production", async () => {
    const { gtagSpy } = installWindow({
      hostname: "meguribi.jp",
      storageSeed: { "meguribi:ga-dev-optout": "1" },
    });
    const mod = await loadModule();
    expect(mod.isDevOptedOut()).toBe(true);
    mod.track("favorite_add", { store_slug: "ebisu" });
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

// ────────────────────────────────────────────────────────────────────────────
// 2026-08-26 計測レビュー対応: イベント名SSOTの網羅性 + PV重複防止ガードの純粋関数テスト。
// ────────────────────────────────────────────────────────────────────────────

describe("ANALYTICS_EVENT_NAMES (SSOT)", () => {
  it("contains exactly the known 12 event names, with no duplicates", () => {
    // 2026-08-26 計測レビューR2対応: 露出2種（official_site_view / second_venue_view）を追加し
    // 10種→12種になった。scripts/analytics_weekly_report.py の KNOWN_CUSTOM_EVENTS
    // （= この12種 + legacy alias "report_read"）と一致させること。
    const expected = [
      "store_view",
      "report_view",
      "favorite_add",
      "favorite_remove",
      "compare_add_store",
      "range_mode_change",
      "cost_sim_interact",
      "related_store_click",
      "official_site_click",
      "second_venue_click",
      "official_site_view",
      "second_venue_view",
    ];
    expect([...ANALYTICS_EVENT_NAMES].sort()).toEqual([...expected].sort());
    expect(new Set(ANALYTICS_EVENT_NAMES).size).toBe(ANALYTICS_EVENT_NAMES.length);
  });

  it("type-level: AnalyticsEventName stays exhaustively covered (compile-time guard)", () => {
    // 実行時のアサーションは無いが、AnalyticsEventName の union に増減があれば
    // 下のswitchが型エラーになりビルド/型チェックが落ちる＝配列と型のズレを検知する仕掛け。
    const assertExhaustive = (name: AnalyticsEventName): void => {
      switch (name) {
        case "store_view":
        case "report_view":
        case "favorite_add":
        case "favorite_remove":
        case "compare_add_store":
        case "range_mode_change":
        case "cost_sim_interact":
        case "related_store_click":
        case "official_site_click":
        case "second_venue_click":
        case "official_site_view":
        case "second_venue_view":
          return;
        default: {
          const _exhaustive: never = name;
          void _exhaustive;
        }
      }
    };
    expect(typeof assertExhaustive).toBe("function");
  });
});

describe("shouldSendPageView (PVの重複防止ガード)", () => {
  it("sends on the first run for a given pathname (lastSentPath is null)", () => {
    expect(
      shouldSendPageView({ enabled: true, pathname: "/reports", lastSentPath: null }),
    ).toBe(true);
  });

  it("does NOT send again when pathname is unchanged (query-only navigation)", () => {
    // /reports の検索文字入力や /compare の ?stores= 変更のような query-only な
    // router.replace を模している。ここが true に戻るとPV水増しバグが再発する。
    expect(
      shouldSendPageView({ enabled: true, pathname: "/reports", lastSentPath: "/reports" }),
    ).toBe(false);
  });

  it("sends again once pathname actually changes", () => {
    expect(
      shouldSendPageView({ enabled: true, pathname: "/stores", lastSentPath: "/reports" }),
    ).toBe(true);
  });

  it("never sends when GA is not enabled, regardless of pathname", () => {
    expect(
      shouldSendPageView({ enabled: false, pathname: "/reports", lastSentPath: null }),
    ).toBe(false);
  });
});

// ────────────────────────────────────────────────────────────────────────────
// 2026-08-26 計測レビューR2対応: sendPageView が公式の page_view イベント方式で送ることを固定する。
// ────────────────────────────────────────────────────────────────────────────

describe("sendPageView (公式 page_view イベント方式)", () => {
  afterEach(() => {
    delete (globalThis as { window?: unknown }).window;
    delete (globalThis as { document?: unknown }).document;
  });

  it("SPA遷移では gtag('event','page_view',{page_location,page_title}) を送る（config の page_path は非公式）", async () => {
    const { gtagSpy, win } = installWindow({ hostname: "meguribi.jp" });
    // getBrowserWindow() が window.location.origin / document.title を読むため両方用意する。
    win.location = { hostname: "meguribi.jp", origin: "https://meguribi.jp" };
    (globalThis as { document?: unknown }).document = { title: "テストページ" };
    const mod = await loadModule();
    mod.sendPageView("/stores?tab=area");
    expect(gtagSpy).toHaveBeenCalledWith("event", "page_view", {
      page_location: "https://meguribi.jp/stores?tab=area",
      page_title: "テストページ",
    });
    // 非公式パラメータ page_path や config 方式を使っていないことも確認する。
    expect(gtagSpy).not.toHaveBeenCalledWith(
      "config",
      expect.anything(),
      expect.objectContaining({ page_path: expect.anything() }),
    );
  });

  it("GA無効時は sendPageView も no-op", async () => {
    const { gtagSpy } = installWindow({ hostname: "localhost" });
    const mod = await loadModule();
    mod.sendPageView("/stores");
    expect(gtagSpy).not.toHaveBeenCalled();
  });
});

// ────────────────────────────────────────────────────────────────────────────
// 2026-08-26 計測レビューR2対応: official_site_view / second_venue_view の露出判定
// （shouldFireExposure）の境界値テスト。50%以上・1000ms以上・未発火、の全てを満たす時だけ true。
// ────────────────────────────────────────────────────────────────────────────

describe("shouldFireExposure (露出2面の発火条件)", () => {
  it("50%かつ1000ms以上・未発火なら true", () => {
    expect(
      shouldFireExposure({ intersectionRatio: 0.5, visibleMs: 1000, alreadyFired: false }),
    ).toBe(true);
    expect(
      shouldFireExposure({ intersectionRatio: 1, visibleMs: 5000, alreadyFired: false }),
    ).toBe(true);
  });

  it("交差率が49%（しきい値未満）なら false", () => {
    expect(
      shouldFireExposure({ intersectionRatio: 0.49, visibleMs: 1000, alreadyFired: false }),
    ).toBe(false);
  });

  it("表示継続が999ms（しきい値未満）なら false", () => {
    expect(
      shouldFireExposure({ intersectionRatio: 1, visibleMs: 999, alreadyFired: false }),
    ).toBe(false);
  });

  it("条件を満たしていても既発火なら false（1回きり）", () => {
    expect(
      shouldFireExposure({ intersectionRatio: 1, visibleMs: 5000, alreadyFired: true }),
    ).toBe(false);
  });
});
