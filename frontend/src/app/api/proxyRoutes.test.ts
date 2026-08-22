// frontend/src/app/api/proxyRoutes.test.ts
//
// D-01（透過プロキシ route.ts 10本のヘルパー集約）と C-13（BACKEND_URL 既定値の統一）の
// 番犬テスト。
//
// 10本は「BACKEND_URL → fetch(next.revalidate) → arrayBuffer → content-type 転記 →
// ok のときだけ cache-control 付与 → 例外は 502 {ok:false,error:'proxy-error'}」という
// 同じ骨格で、違うのは (a) レート制限の有無と上限 (b) クエリの組み立て方
// (c) content-type 既定値 だけ。集約でこの差分が1つでもズレたら落ちるように、
// ルートごとに「叩かれた URL / revalidate / status / content-type / cache-control / body」
// を表で固定する。集約の前後どちらでも緑であること。
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

// route モジュールは読み込み時に BACKEND_URL を評価するので、import より先に設定する。
// 末尾スラッシュ付きにして「除去されること」も同時に固定する。
process.env.BACKEND_URL = "http://backend.test:5000/";

type RouteSpec = {
  /** テスト表示名 */
  name: string;
  /** route.ts の場所 */
  modulePath: string;
  /** リクエスト URL（クエリ込み） */
  requestUrl: string;
  /** バックエンドへ実際に投げられるべき URL */
  expectedTargetUrl: string;
  /** fetch(init.next.revalidate) の期待値 */
  expectedRevalidate: number;
  /** ok のとき付与される cache-control */
  expectedCacheHeader: string;
  /** バックエンドが content-type を返さなかったときに補われる値（無ければ null） */
  expectedContentTypeFallback: string | null;
};

const BASE = "http://backend.test:5000";

const ROUTES: RouteSpec[] = [
  {
    name: "/api/range",
    modulePath: "./range/route",
    requestUrl: "http://localhost:3000/api/range?store=shibuya&limit=240",
    expectedTargetUrl: `${BASE}/api/range?store=shibuya&limit=240`,
    expectedRevalidate: 240,
    expectedCacheHeader: "public, s-maxage=240, stale-while-revalidate=300",
    expectedContentTypeFallback: null,
  },
  {
    name: "/api/range_multi",
    modulePath: "./range_multi/route",
    requestUrl: "http://localhost:3000/api/range_multi?stores=shibuya,ueno",
    expectedTargetUrl: `${BASE}/api/range_multi?stores=shibuya%2Cueno`,
    expectedRevalidate: 240,
    expectedCacheHeader: "public, s-maxage=240, stale-while-revalidate=300",
    expectedContentTypeFallback: null,
  },
  {
    name: "/api/forecast_today",
    modulePath: "./forecast_today/route",
    requestUrl: "http://localhost:3000/api/forecast_today?store=shibuya",
    expectedTargetUrl: `${BASE}/api/forecast_today?store=shibuya`,
    expectedRevalidate: 300,
    expectedCacheHeader: "public, s-maxage=300, stale-while-revalidate=900",
    expectedContentTypeFallback: null,
  },
  {
    name: "/api/forecast_today_multi",
    modulePath: "./forecast_today_multi/route",
    requestUrl: "http://localhost:3000/api/forecast_today_multi?stores=shibuya,ueno",
    expectedTargetUrl: `${BASE}/api/forecast_today_multi?stores=shibuya%2Cueno`,
    expectedRevalidate: 300,
    expectedCacheHeader: "public, s-maxage=300, stale-while-revalidate=900",
    expectedContentTypeFallback: null,
  },
  {
    name: "/api/forecast_next_hour",
    modulePath: "./forecast_next_hour/route",
    requestUrl: "http://localhost:3000/api/forecast_next_hour?store=shibuya",
    expectedTargetUrl: `${BASE}/api/forecast_next_hour?store=shibuya`,
    expectedRevalidate: 300,
    expectedCacheHeader: "public, s-maxage=300, stale-while-revalidate=900",
    expectedContentTypeFallback: null,
  },
  {
    name: "/api/forecast_snapshot",
    modulePath: "./forecast_snapshot/route",
    requestUrl: "http://localhost:3000/api/forecast_snapshot?store=shibuya&date=20260819",
    expectedTargetUrl: `${BASE}/api/forecast_snapshot?store=shibuya&date=20260819`,
    expectedRevalidate: 86400,
    expectedCacheHeader: "public, s-maxage=86400, stale-while-revalidate=604800",
    expectedContentTypeFallback: null,
  },
  {
    name: "/api/forecast_accuracy",
    modulePath: "./forecast_accuracy/route",
    requestUrl: "http://localhost:3000/api/forecast_accuracy",
    expectedTargetUrl: `${BASE}/api/forecast_accuracy`,
    expectedRevalidate: 3600,
    expectedCacheHeader: "public, s-maxage=3600, stale-while-revalidate=7200",
    expectedContentTypeFallback: null,
  },
  {
    name: "/api/megribi_score",
    modulePath: "./megribi_score/route",
    requestUrl: "http://localhost:3000/api/megribi_score?stores=shibuya",
    expectedTargetUrl: `${BASE}/api/megribi_score?stores=shibuya`,
    expectedRevalidate: 180,
    expectedCacheHeader: "public, s-maxage=180, stale-while-revalidate=600",
    expectedContentTypeFallback: null,
  },
  {
    name: "/api/holiday_status",
    modulePath: "./holiday_status/route",
    requestUrl: "http://localhost:3000/api/holiday_status?date=2026-08-19",
    expectedTargetUrl: `${BASE}/api/holiday_status?date=2026-08-19`,
    expectedRevalidate: 3600,
    expectedCacheHeader: "public, s-maxage=3600, stale-while-revalidate=7200",
    expectedContentTypeFallback: null,
  },
  {
    name: "/api/second_venues",
    modulePath: "./second_venues/route",
    requestUrl: "http://localhost:3000/api/second_venues?store=shibuya",
    expectedTargetUrl: `${BASE}/api/second_venues?store=shibuya`,
    expectedRevalidate: 3600,
    expectedCacheHeader: "public, s-maxage=3600, stale-while-revalidate=7200",
    expectedContentTypeFallback: "application/json",
  },
];

/** クエリ無しで叩いたときに組み立てられる URL（? の有無まで固定する） */
const NO_QUERY_TARGETS: Record<string, string> = {
  "/api/range": `${BASE}/api/range`,
  "/api/range_multi": `${BASE}/api/range_multi`,
  "/api/megribi_score": `${BASE}/api/megribi_score`,
  // store 指定が無いと DEFAULT_STORE が入る
  "/api/forecast_today_multi": `${BASE}/api/forecast_today_multi?stores=`,
  "/api/forecast_snapshot": `${BASE}/api/forecast_snapshot?store=__DEFAULT__&date=`,
  "/api/forecast_today": `${BASE}/api/forecast_today?store=__DEFAULT__`,
  "/api/forecast_next_hour": `${BASE}/api/forecast_next_hour?store=__DEFAULT__`,
  // date 未指定ならクエリ自体が付かない
  "/api/holiday_status": `${BASE}/api/holiday_status`,
  "/api/forecast_accuracy": `${BASE}/api/forecast_accuracy`,
  // store 未指定でも空の store= が付く
  "/api/second_venues": `${BASE}/api/second_venues?store=`,
};

let NextRequest: typeof import("next/server").NextRequest;
let DEFAULT_STORE: string;

beforeAll(async () => {
  ({ NextRequest } = await import("next/server"));
  ({ DEFAULT_STORE } = await import("@/app/config/stores"));
});

type FetchCall = { url: string; init: RequestInit & { next?: { revalidate?: number } } };

function installFetch(responder: () => Response | Promise<Response>): FetchCall[] {
  const calls: FetchCall[] = [];
  vi.stubGlobal("fetch", (url: string, init: FetchCall["init"]) => {
    calls.push({ url: String(url), init: init ?? {} });
    return Promise.resolve(responder());
  });
  return calls;
}

async function callRoute(spec: RouteSpec, url = spec.requestUrl): Promise<Response> {
  const mod = (await import(/* @vite-ignore */ spec.modulePath)) as {
    GET: (req: unknown) => Promise<Response>;
  };
  return mod.GET(new NextRequest(url));
}

beforeEach(() => {
  vi.unstubAllGlobals();
});

describe.each(ROUTES)("$name プロキシの契約", (spec) => {
  it("200: 叩く URL・revalidate・status・content-type・cache-control・body が固定値どおり", async () => {
    const payload = JSON.stringify({ ok: true, data: [1, 2, 3] });
    const calls = installFetch(
      () => new Response(payload, { status: 200, headers: { "content-type": "application/json" } }),
    );

    const res = await callRoute(spec);

    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe(spec.expectedTargetUrl);
    expect(calls[0].init.next?.revalidate).toBe(spec.expectedRevalidate);

    expect(res.status).toBe(200);
    expect(res.headers.get("content-type")).toBe("application/json");
    expect(res.headers.get("cache-control")).toBe(spec.expectedCacheHeader);
    expect(await res.text()).toBe(payload);
  });

  it("非 200: status は素通し、cache-control は付かない", async () => {
    const payload = JSON.stringify({ ok: false, error: "boom" });
    installFetch(
      () => new Response(payload, { status: 503, headers: { "content-type": "application/json" } }),
    );

    const res = await callRoute(spec);

    expect(res.status).toBe(503);
    expect(res.headers.get("cache-control")).toBeNull();
    expect(await res.text()).toBe(payload);
  });

  it("HTTP 200 だが本文が ok:false（小さい本文）: cache-control は付かない", async () => {
    // 2026-08-22 総合レビュー対応: backend が 200 のまま ok:false を返す実在経路
    // （/api/second_venues の設定不備時など）を CDN に焼き付けないための番犬。
    const payload = JSON.stringify({ ok: false, error: "not-configured" });
    installFetch(
      () => new Response(payload, { status: 200, headers: { "content-type": "application/json" } }),
    );

    const res = await callRoute(spec);

    expect(res.status).toBe(200);
    expect(res.headers.get("cache-control")).toBeNull();
    expect(await res.text()).toBe(payload);
  });

  it("HTTP 200 かつ本文が大きい（4KB以上）: ok:false 形でもパースせず通常通りキャッシュする", async () => {
    // /api/range_multi の大量行応答を毎回パースしない、という性能上のトレードオフを固定する。
    const payload = JSON.stringify({ ok: false, data: "x".repeat(5000) }); // 4KB超になる想定
    expect(payload.length).toBeGreaterThanOrEqual(4096);
    installFetch(
      () => new Response(payload, { status: 200, headers: { "content-type": "application/json" } }),
    );

    const res = await callRoute(spec);

    expect(res.status).toBe(200);
    expect(res.headers.get("cache-control")).toBe(spec.expectedCacheHeader);
  });

  it("HTTP 200 かつ本文が JSON でない（小さい）: パース失敗しても通常通りキャッシュする", async () => {
    installFetch(() => new Response("not json", { status: 200, headers: { "content-type": "text/plain" } }));

    const res = await callRoute(spec);

    expect(res.status).toBe(200);
    expect(res.headers.get("cache-control")).toBe(spec.expectedCacheHeader);
  });

  it("fetch 例外: 502 と {ok:false,error:'proxy-error',detail}", async () => {
    vi.stubGlobal("fetch", () => Promise.reject(new Error("ECONNREFUSED")));

    const res = await callRoute(spec);

    expect(res.status).toBe(502);
    expect(await res.json()).toEqual({
      ok: false,
      error: "proxy-error",
      detail: "ECONNREFUSED",
    });
  });

  it("content-type の扱い（second_venues だけ application/json を補う）", async () => {
    // 文字列 body だと Response が text/plain;charset=UTF-8 を自動で付けてしまうため、
    // content-type が付かない ArrayBuffer 系の body で「バックエンドが返さなかった」を作る。
    installFetch(() => new Response(new TextEncoder().encode("raw"), { status: 200 }));

    const res = await callRoute(spec);

    if (spec.expectedContentTypeFallback === null) {
      expect(res.headers.get("content-type")).toBeNull();
    } else {
      expect(res.headers.get("content-type")).toBe(spec.expectedContentTypeFallback);
    }
  });

  it("クエリ無しのときの URL 組み立て（? の有無まで）", async () => {
    const calls = installFetch(() => new Response("{}", { status: 200 }));
    const base = new URL(spec.requestUrl);
    await callRoute(spec, `${base.origin}${base.pathname}`);

    const expected = NO_QUERY_TARGETS[spec.name].replace("__DEFAULT__", DEFAULT_STORE);
    expect(calls[0].url).toBe(expected);
  });
});

describe("BACKEND_URL の末尾スラッシュは除去される", () => {
  it("すべてのルートで二重スラッシュにならない", async () => {
    for (const spec of ROUTES) {
      const calls = installFetch(() => new Response("{}", { status: 200 }));
      await callRoute(spec);
      expect(calls[0].url.startsWith(`${BASE}/api/`)).toBe(true);
      expect(calls[0].url).not.toContain("5000//");
      vi.unstubAllGlobals();
    }
  });
});

/**
 * レート制限は「どのルートに付いていて上限がいくつか」だけが差分なので、
 * 上限そのものを 429 の X-RateLimit-Limit で固定する。
 * IP はルートごとに変えて、他テストとカウンタを共有しないようにする。
 */
const RATE_LIMITS: Record<string, number | null> = {
  "/api/range": 3, // 既定（API_RATE_LIMIT_PER_MINUTE）を使う唯一のルート
  "/api/range_multi": 30,
  "/api/forecast_today": 30,
  "/api/forecast_today_multi": 20,
  "/api/forecast_next_hour": 30,
  "/api/forecast_snapshot": 30,
  "/api/megribi_score": 30,
  "/api/forecast_accuracy": null, // レート制限なし
  "/api/holiday_status": null,
  "/api/second_venues": null,
};

describe.each(ROUTES)("$name のレート制限", (spec) => {
  it("上限と 429 の有無が変わっていない", async () => {
    process.env.API_RATE_LIMIT_PER_MINUTE = "3";
    installFetch(() => new Response("{}", { status: 200 }));

    const mod = (await import(/* @vite-ignore */ spec.modulePath)) as {
      GET: (req: unknown) => Promise<Response>;
    };
    const ip = `10.0.0.${ROUTES.indexOf(spec) + 1}`;
    const call = () =>
      mod.GET(new NextRequest(spec.requestUrl, { headers: { "x-forwarded-for": ip } }));

    const limit = RATE_LIMITS[spec.name];

    if (limit === null) {
      // レート制限なし: 何回叩いても 429 にならない
      for (let i = 0; i < 5; i += 1) {
        expect((await call()).status).not.toBe(429);
      }
      return;
    }

    for (let i = 0; i < limit; i += 1) {
      expect((await call()).status).toBe(200);
    }
    const blocked = await call();
    expect(blocked.status).toBe(429);
    expect(blocked.headers.get("X-RateLimit-Limit")).toBe(String(limit));
    expect(blocked.headers.get("X-RateLimit-Remaining")).toBe("0");
    expect(await blocked.text()).toBe("Too Many Requests");
  });
});
