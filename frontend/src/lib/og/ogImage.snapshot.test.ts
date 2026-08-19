import { describe, expect, it, vi } from "vitest";

/**
 * 番犬テスト（D-06）: 8本の opengraph-image ルートが ImageResponse に渡す JSX の要素ツリーを
 * まるごとダンプして固定する。
 *
 * ImageResponse は同一の要素ツリーから決定的に PNG を描くため、要素ツリーが 1 文字も変わらなければ
 * 出力画像も同一。共通コンポーネント（lib/og/HubOgImage・ReportOgImage）へ寄せる前後で、
 * このダンプが一致することを持って「見た目は変わっていない」ことの証明とする。
 *
 * next/og の ImageResponse を「引数を保持するだけ」のクラスに差し替えて要素ツリーを取り出す。
 */

class CapturedImageResponse {
  constructor(
    public element: unknown,
    public options: unknown,
  ) {}
}

vi.mock("next/og", () => ({ ImageResponse: CapturedImageResponse }));

type OgModule = {
  default: (props?: unknown) => unknown | Promise<unknown>;
  alt?: string;
  size?: unknown;
  contentType?: string;
  runtime?: string;
};

/**
 * React 要素ツリーを JSON 化する（Symbol の $$typeof や dev 専用フィールドは落とす）。
 *
 * children は React が描画時に無視する差（null/undefined/boolean の混入、
 * 「1要素の配列」と「単一要素」の違い）を正規化する。ここを厳密に比較すると、
 * 条件付きレンダリング（`cond ? <x/> : null`）へ書き換えただけで差分が出てしまい、
 * 「見た目が変わっていない」ことの判定にならないため。
 */
function serializeChildren(node: unknown): unknown {
  const flat = (Array.isArray(node) ? node.flat(Infinity) : [node]).filter(
    (c) => c !== null && c !== undefined && typeof c !== "boolean",
  );
  if (flat.length === 0) return null;
  if (flat.length === 1) return serializeElement(flat[0]);
  return flat.map(serializeElement);
}

function serializeElement(node: unknown): unknown {
  if (node === null || node === undefined) return node;
  if (Array.isArray(node)) return serializeChildren(node);
  if (typeof node !== "object") return node;

  const el = node as { type?: unknown; key?: unknown; props?: Record<string, unknown> };
  if (el.type !== undefined && el.props !== undefined) {
    const props: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(el.props)) {
      props[k] = k === "children" ? serializeChildren(v) : v;
    }
    return {
      type: typeof el.type === "string" ? el.type : `<${(el.type as { name?: string })?.name ?? "fn"}>`,
      key: el.key ?? null,
      props,
    };
  }
  return node;
}

async function capture(mod: OgModule, props?: unknown) {
  const res = (await mod.default(props)) as CapturedImageResponse;
  return {
    alt: mod.alt,
    size: mod.size,
    contentType: mod.contentType,
    runtime: mod.runtime,
    options: res.options,
    element: serializeElement(res.element),
  };
}

describe("OG 画像 8本の要素ツリースナップショット", () => {
  it("ハブ4本（/ , /stores, /reports, /blog）が固定値と一致する", async () => {
    const dump: Record<string, unknown> = {};
    for (const [key, path] of [
      ["/", "@/app/opengraph-image"],
      ["/stores", "@/app/stores/opengraph-image"],
      ["/reports", "@/app/reports/opengraph-image"],
      ["/blog", "@/app/blog/opengraph-image"],
    ] as const) {
      dump[key] = await capture((await import(/* @vite-ignore */ path)) as OgModule);
    }
    await expect(JSON.stringify(dump, null, 1)).toMatchFileSnapshot(
      "./__snapshots__/og.hub.json",
    );
  });

  it("動的4本（store / daily / weekly / blog記事）が固定値と一致する", async () => {
    // 日付が入る daily / weekly は実行時刻で文言が変わるため、Date を固定する。
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-19T03:00:00Z"));
    try {
      const dump: Record<string, unknown> = {};
      const store = (await import("@/app/store/[id]/opengraph-image")) as OgModule;
      const daily = (await import("@/app/reports/daily/[store_slug]/opengraph-image")) as OgModule;
      const weekly = (await import("@/app/reports/weekly/[store_slug]/opengraph-image")) as OgModule;
      const blog = (await import("@/app/blog/[slug]/opengraph-image")) as OgModule;

      for (const slug of ["shibuya", "ay_chiba", "__unknown__"]) {
        dump[`/store/${slug}`] = await capture(store, { params: Promise.resolve({ id: slug }) });
        dump[`/reports/daily/${slug}`] = await capture(daily, {
          params: Promise.resolve({ store_slug: slug }),
        });
        dump[`/reports/weekly/${slug}`] = await capture(weekly, {
          params: Promise.resolve({ store_slug: slug }),
        });
      }
      for (const slug of ["beginner-complete-guide", "__missing__"]) {
        dump[`/blog/${slug}`] = await capture(blog, { params: Promise.resolve({ slug }) });
      }

      await expect(JSON.stringify(dump, null, 1)).toMatchFileSnapshot(
        "./__snapshots__/og.dynamic.json",
      );
    } finally {
      vi.useRealTimers();
    }
  });
});
