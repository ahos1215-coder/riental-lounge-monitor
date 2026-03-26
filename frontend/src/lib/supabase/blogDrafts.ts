/**
 * Insert rows into Supabase public.blog_drafts (REST).
 * Uses SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY (server-only).
 */

export type BlogDraftRow = {
  store_id: string;
  store_slug: string;
  target_date: string;
  facts_id: string;
  mdx_content: string;
  insight_json: Record<string, unknown>;
  source: string;
  content_type?: "daily" | "weekly" | "editorial";
  is_published?: boolean;
  edition?: string | null;
  public_slug?: string | null;
  line_user_id?: string | null;
  error_message?: string | null;
};

export type AutoBlogDraftView = {
  facts_id: string;
  store_slug: string;
  target_date: string;
  mdx_content: string;
  source: string;
  updated_at?: string;
  created_at?: string;
};

export type PublishedReportType = "daily" | "weekly";

export type PublishedReportRow = {
  facts_id: string;
  store_slug: string;
  target_date: string;
  mdx_content: string;
  insight_json: Record<string, unknown>;
  source: string;
  content_type: PublishedReportType;
  edition?: string;
  public_slug?: string;
  created_at?: string;
};

export type PublishedEditorialRow = {
  facts_id: string;
  public_slug: string;
  store_slug: string;
  target_date: string;
  mdx_content: string;
  insight_json: Record<string, unknown>;
  source: string;
  created_at?: string;
};

function getEnv(name: string): string | undefined {
  const v = process.env[name];
  return v?.trim() || undefined;
}

function serviceRoleKey(): string | undefined {
  return getEnv("SUPABASE_SERVICE_ROLE_KEY") || getEnv("SUPABASE_SERVICE_KEY");
}

export function isBlogDraftsConfigured(): boolean {
  return Boolean(getEnv("SUPABASE_URL") && serviceRoleKey());
}

function endpointUrl(): { endpoint: string; key: string } | null {
  const url = getEnv("SUPABASE_URL");
  const key = serviceRoleKey();
  if (!url || !key) return null;
  return { endpoint: `${url.replace(/\/+$/, "")}/rest/v1/blog_drafts`, key };
}

async function upsertByFactsId(row: BlogDraftRow): Promise<{ ok: true; id: string } | { ok: false; error: string }> {
  const conf = endpointUrl();
  if (!conf) {
    return { ok: false, error: "Supabase env missing (SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY)" };
  }

  const { endpoint, key } = conf;
  const body = {
    store_id: row.store_id,
    store_slug: row.store_slug,
    target_date: row.target_date,
    facts_id: row.facts_id,
    mdx_content: row.mdx_content,
    insight_json: row.insight_json,
    source: row.source,
    content_type: row.content_type ?? "editorial",
    is_published: row.is_published ?? false,
    edition: row.edition ?? null,
    public_slug: row.public_slug ?? null,
    line_user_id: row.line_user_id ?? null,
    error_message: row.error_message ?? null,
  };

  try {
    // 先に同一 facts_id を更新（SEO 用に固定IDを上書き）
    const patchUrl = `${endpoint}?facts_id=eq.${encodeURIComponent(row.facts_id)}`;
    const patchRes = await fetch(patchUrl, {
      method: "PATCH",
      headers: {
        apikey: key,
        Authorization: `Bearer ${key}`,
        "Content-Type": "application/json",
        Prefer: "return=representation",
      },
      body: JSON.stringify(body),
    });

    const patchTxt = await patchRes.text();
    if (!patchRes.ok) {
      return { ok: false, error: `supabase patch ${patchRes.status}: ${patchTxt.slice(0, 500)}` };
    }

    try {
      const parsed = JSON.parse(patchTxt) as unknown;
      if (Array.isArray(parsed) && parsed.length > 0 && parsed[0] && typeof parsed[0] === "object") {
        const first = parsed[0] as Record<string, unknown>;
        const id = typeof first.id === "string" ? first.id : "updated";
        return { ok: true, id };
      }
    } catch {
      // ignore and continue insert fallback
    }

    // 未作成なら insert
    const insertRes = await fetch(endpoint, {
      method: "POST",
      headers: {
        apikey: key,
        Authorization: `Bearer ${key}`,
        "Content-Type": "application/json",
        Prefer: "return=representation",
      },
      body: JSON.stringify(body),
    });

    const insertTxt = await insertRes.text();
    if (!insertRes.ok) {
      return { ok: false, error: `supabase insert ${insertRes.status}: ${insertTxt.slice(0, 500)}` };
    }

    let id = "";
    try {
      const parsed = JSON.parse(insertTxt) as unknown;
      if (Array.isArray(parsed) && parsed[0] && typeof parsed[0] === "object") {
        const first = parsed[0] as Record<string, unknown>;
        id = typeof first.id === "string" ? first.id : "";
      }
    } catch {
      // ignore
    }
    return { ok: true, id: id || "inserted" };
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    return { ok: false, error: msg };
  }
}

export async function insertBlogDraft(row: BlogDraftRow): Promise<{ ok: true; id: string } | { ok: false; error: string }> {
  return upsertByFactsId(row);
}

export async function fetchLatestAutoBlogDrafts(limit = 12): Promise<AutoBlogDraftView[]> {
  const conf = endpointUrl();
  if (!conf) return [];
  const { endpoint, key } = conf;
  const capped = Math.max(1, Math.min(limit, 40));
  // 定時 cron と GHA 手動再試行は同一の自動下書きとして扱う
  const url =
    `${endpoint}?select=facts_id,store_slug,target_date,mdx_content,source,created_at,error_message` +
    `&source=in.(github_actions_cron,github_actions_retry)&error_message=is.null&mdx_content=not.eq.` +
    `&order=created_at.desc&limit=${capped}`;
  try {
    const res = await fetch(url, {
      method: "GET",
      cache: "no-store",
      headers: {
        apikey: key,
        Authorization: `Bearer ${key}`,
        Accept: "application/json",
      },
    });
    if (!res.ok) return [];
    const parsed = (await res.json()) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((v): v is Record<string, unknown> => Boolean(v && typeof v === "object"))
      .map((v) => ({
        facts_id: typeof v.facts_id === "string" ? v.facts_id : "",
        store_slug: typeof v.store_slug === "string" ? v.store_slug : "",
        target_date: typeof v.target_date === "string" ? v.target_date : "",
        mdx_content: typeof v.mdx_content === "string" ? v.mdx_content : "",
        source: typeof v.source === "string" ? v.source : "",
        created_at: typeof v.created_at === "string" ? v.created_at : undefined,
      }))
      .filter((v) => v.facts_id && v.store_slug && v.mdx_content);
  } catch {
    return [];
  }
}

export async function fetchLatestAutoBlogDraftByStoreSlug(storeSlug: string): Promise<AutoBlogDraftView | null> {
  const conf = endpointUrl();
  const slug = storeSlug.trim().toLowerCase();
  if (!conf || !slug) return null;
  const { endpoint, key } = conf;
  const url =
    `${endpoint}?select=facts_id,store_slug,target_date,mdx_content,source,created_at,error_message` +
    `&store_slug=eq.${encodeURIComponent(slug)}` +
    `&source=in.(github_actions_cron,github_actions_retry)` +
    `&error_message=is.null&mdx_content=not.eq.` +
    `&order=created_at.desc&limit=1`;
  try {
    const res = await fetch(url, {
      method: "GET",
      cache: "no-store",
      headers: {
        apikey: key,
        Authorization: `Bearer ${key}`,
        Accept: "application/json",
      },
    });
    if (!res.ok) return null;
    const parsed = (await res.json()) as unknown;
    if (!Array.isArray(parsed) || !parsed[0] || typeof parsed[0] !== "object") return null;
    const v = parsed[0] as Record<string, unknown>;
    const row: AutoBlogDraftView = {
      facts_id: typeof v.facts_id === "string" ? v.facts_id : "",
      store_slug: typeof v.store_slug === "string" ? v.store_slug : "",
      target_date: typeof v.target_date === "string" ? v.target_date : "",
      mdx_content: typeof v.mdx_content === "string" ? v.mdx_content : "",
      source: typeof v.source === "string" ? v.source : "",
      created_at: typeof v.created_at === "string" ? v.created_at : undefined,
    };
    return row.facts_id && row.store_slug && row.mdx_content ? row : null;
  } catch {
    return null;
  }
}

export async function fetchAutoBlogDraftByFactsId(factsId: string): Promise<AutoBlogDraftView | null> {
  const conf = endpointUrl();
  if (!conf || !factsId.trim()) return null;
  const { endpoint, key } = conf;
  const url =
    `${endpoint}?select=facts_id,store_slug,target_date,mdx_content,source,created_at,error_message` +
    `&facts_id=eq.${encodeURIComponent(factsId)}&error_message=is.null&limit=1`;
  try {
    const res = await fetch(url, {
      method: "GET",
      cache: "no-store",
      headers: {
        apikey: key,
        Authorization: `Bearer ${key}`,
        Accept: "application/json",
      },
    });
    if (!res.ok) return null;
    const parsed = (await res.json()) as unknown;
    if (!Array.isArray(parsed) || !parsed[0] || typeof parsed[0] !== "object") return null;
    const v = parsed[0] as Record<string, unknown>;
    const row: AutoBlogDraftView = {
      facts_id: typeof v.facts_id === "string" ? v.facts_id : "",
      store_slug: typeof v.store_slug === "string" ? v.store_slug : "",
      target_date: typeof v.target_date === "string" ? v.target_date : "",
      mdx_content: typeof v.mdx_content === "string" ? v.mdx_content : "",
      source: typeof v.source === "string" ? v.source : "",
      created_at: typeof v.created_at === "string" ? v.created_at : undefined,
    };
    return row.facts_id && row.store_slug && row.mdx_content ? row : null;
  } catch {
    return null;
  }
}

function toRecord(value: unknown): Record<string, unknown> {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return {};
}

export async function fetchLatestPublishedReportByStore(
  storeSlug: string,
  contentType: PublishedReportType,
): Promise<PublishedReportRow | null> {
  const conf = endpointUrl();
  const slug = storeSlug.trim().toLowerCase();
  if (!conf || !slug) return null;
  const { endpoint, key } = conf;
  const url =
    `${endpoint}?select=facts_id,store_slug,target_date,mdx_content,insight_json,source,content_type,edition,public_slug,created_at` +
    `&store_slug=eq.${encodeURIComponent(slug)}` +
    `&content_type=eq.${encodeURIComponent(contentType)}` +
    `&is_published=eq.true&error_message=is.null` +
    `&order=created_at.desc&limit=1`;
  try {
    const res = await fetch(url, {
      method: "GET",
      cache: "no-store",
      headers: {
        apikey: key,
        Authorization: `Bearer ${key}`,
        Accept: "application/json",
      },
    });
    if (!res.ok) return null;
    const parsed = (await res.json()) as unknown;
    if (!Array.isArray(parsed) || !parsed[0] || typeof parsed[0] !== "object") return null;
    const v = parsed[0] as Record<string, unknown>;
    const ct = typeof v.content_type === "string" ? v.content_type : "";
    if (ct !== "daily" && ct !== "weekly") return null;
    const row: PublishedReportRow = {
      facts_id: typeof v.facts_id === "string" ? v.facts_id : "",
      store_slug: typeof v.store_slug === "string" ? v.store_slug : "",
      target_date: typeof v.target_date === "string" ? v.target_date : "",
      mdx_content: typeof v.mdx_content === "string" ? v.mdx_content : "",
      insight_json: toRecord(v.insight_json),
      source: typeof v.source === "string" ? v.source : "",
      content_type: ct,
      edition: typeof v.edition === "string" ? v.edition : undefined,
      public_slug: typeof v.public_slug === "string" ? v.public_slug : undefined,
      created_at: typeof v.created_at === "string" ? v.created_at : undefined,
    };
    return row.facts_id && row.store_slug ? row : null;
  } catch {
    return null;
  }
}

export async function fetchPublishedEditorialBySlug(slug: string): Promise<PublishedEditorialRow | null> {
  const conf = endpointUrl();
  const normalized = slug.trim().toLowerCase();
  if (!conf || !normalized) return null;
  const { endpoint, key } = conf;
  const url =
    `${endpoint}?select=facts_id,public_slug,store_slug,target_date,mdx_content,insight_json,source,created_at` +
    `&public_slug=eq.${encodeURIComponent(normalized)}` +
    `&content_type=eq.editorial&is_published=eq.true&error_message=is.null&limit=1`;
  try {
    const res = await fetch(url, {
      method: "GET",
      cache: "no-store",
      headers: {
        apikey: key,
        Authorization: `Bearer ${key}`,
        Accept: "application/json",
      },
    });
    if (!res.ok) return null;
    const parsed = (await res.json()) as unknown;
    if (!Array.isArray(parsed) || !parsed[0] || typeof parsed[0] !== "object") return null;
    const v = parsed[0] as Record<string, unknown>;
    const row: PublishedEditorialRow = {
      facts_id: typeof v.facts_id === "string" ? v.facts_id : "",
      public_slug: typeof v.public_slug === "string" ? v.public_slug : "",
      store_slug: typeof v.store_slug === "string" ? v.store_slug : "",
      target_date: typeof v.target_date === "string" ? v.target_date : "",
      mdx_content: typeof v.mdx_content === "string" ? v.mdx_content : "",
      insight_json: toRecord(v.insight_json),
      source: typeof v.source === "string" ? v.source : "",
      created_at: typeof v.created_at === "string" ? v.created_at : undefined,
    };
    return row.public_slug && row.mdx_content ? row : null;
  } catch {
    return null;
  }
}

/**
 * LINE 承認フロー: editorial 下書きを is_published=true に更新する。
 * facts_id で特定する。成功時は public_slug を返す（ページURLに使う）。
 */
export async function publishEditorialByFactsId(
  factsId: string,
): Promise<{ ok: true; publicSlug: string | null } | { ok: false; error: string }> {
  const conf = endpointUrl();
  if (!conf) return { ok: false, error: "Supabase 未設定" };
  const { endpoint, key } = conf;

  const patchUrl = `${endpoint}?facts_id=eq.${encodeURIComponent(factsId)}&content_type=eq.editorial`;
  try {
    const res = await fetch(patchUrl, {
      method: "PATCH",
      headers: {
        apikey: key,
        Authorization: `Bearer ${key}`,
        "Content-Type": "application/json",
        Prefer: "return=representation",
      },
      body: JSON.stringify({ is_published: true }),
    });
    const txt = await res.text();
    if (!res.ok) return { ok: false, error: `supabase patch ${res.status}: ${txt.slice(0, 300)}` };
    try {
      const rows = JSON.parse(txt) as unknown;
      if (Array.isArray(rows) && rows.length > 0) {
        const first = rows[0] as Record<string, unknown>;
        const publicSlug = typeof first.public_slug === "string" ? first.public_slug : null;
        return { ok: true, publicSlug };
      }
    } catch {
      // ignore parse error
    }
    return { ok: true, publicSlug: null };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

/**
 * LINE 承認フロー: public_slug で特定して is_published=true に更新する。
 */
export async function publishEditorialBySlug(
  publicSlug: string,
): Promise<{ ok: true; publicSlug: string } | { ok: false; error: string }> {
  const conf = endpointUrl();
  if (!conf) return { ok: false, error: "Supabase 未設定" };
  const { endpoint, key } = conf;

  const patchUrl =
    `${endpoint}?public_slug=eq.${encodeURIComponent(publicSlug)}&content_type=eq.editorial`;
  try {
    const res = await fetch(patchUrl, {
      method: "PATCH",
      headers: {
        apikey: key,
        Authorization: `Bearer ${key}`,
        "Content-Type": "application/json",
        Prefer: "return=representation",
      },
      body: JSON.stringify({ is_published: true }),
    });
    const txt = await res.text();
    if (!res.ok) return { ok: false, error: `supabase patch ${res.status}: ${txt.slice(0, 300)}` };
    return { ok: true, publicSlug };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

/**
 * LINE 承認フロー: 特定 LINE ユーザーの最新 editorial 未公開下書きを取得する。
 * "公開" メッセージ受信時に、どの下書きを承認するか特定するために使う。
 */
export type ReportListItem = {
  store_slug: string;
  target_date: string;
  edition?: string;
  created_at?: string;
  heading: string | null;
};

/**
 * 全店舗の最新の公開済みレポートを取得（一覧ページ用）。
 * 各店舗の最新1件のみ返す（created_at desc で取得し、フロントで重複除去）。
 */
export async function fetchAllLatestPublishedReports(
  contentType: PublishedReportType,
  limit = 50,
): Promise<ReportListItem[]> {
  const conf = endpointUrl();
  if (!conf) return [];
  const { endpoint, key } = conf;
  const url =
    `${endpoint}?select=store_slug,target_date,edition,created_at,mdx_content` +
    `&content_type=eq.${encodeURIComponent(contentType)}` +
    `&is_published=eq.true&error_message=is.null&mdx_content=not.eq.` +
    `&order=created_at.desc&limit=${Math.min(limit, 200)}`;
  try {
    const res = await fetch(url, {
      method: "GET",
      next: { revalidate: 300 },
      headers: {
        apikey: key,
        Authorization: `Bearer ${key}`,
        Accept: "application/json",
      },
    });
    if (!res.ok) return [];
    const parsed = (await res.json()) as unknown;
    if (!Array.isArray(parsed)) return [];

    const seen = new Set<string>();
    const items: ReportListItem[] = [];
    for (const raw of parsed) {
      if (!raw || typeof raw !== "object") continue;
      const v = raw as Record<string, unknown>;
      const slug = typeof v.store_slug === "string" ? v.store_slug : "";
      if (!slug || seen.has(slug)) continue;
      seen.add(slug);
      const mdx = typeof v.mdx_content === "string" ? v.mdx_content : "";
      let heading: string | null = null;
      for (const line of mdx.split("\n")) {
        const m = line.match(/^#{1,3}\s+(.+)/);
        if (m) { heading = m[1].trim(); break; }
      }
      items.push({
        store_slug: slug,
        target_date: typeof v.target_date === "string" ? v.target_date : "",
        edition: typeof v.edition === "string" ? v.edition : undefined,
        created_at: typeof v.created_at === "string" ? v.created_at : undefined,
        heading,
      });
    }
    return items;
  } catch {
    return [];
  }
}

export async function fetchLatestUnpublishedEditorialByLineUser(
  lineUserId: string,
): Promise<{ facts_id: string; public_slug: string | null; store_slug: string; target_date: string } | null> {
  const conf = endpointUrl();
  if (!conf || !lineUserId.trim()) return null;
  const { endpoint, key } = conf;
  const url =
    `${endpoint}?select=facts_id,public_slug,store_slug,target_date` +
    `&line_user_id=eq.${encodeURIComponent(lineUserId)}` +
    `&content_type=eq.editorial&is_published=eq.false` +
    `&error_message=is.null&mdx_content=not.eq.` +
    `&order=created_at.desc&limit=1`;
  try {
    const res = await fetch(url, {
      method: "GET",
      cache: "no-store",
      headers: {
        apikey: key,
        Authorization: `Bearer ${key}`,
        Accept: "application/json",
      },
    });
    if (!res.ok) return null;
    const parsed = (await res.json()) as unknown;
    if (!Array.isArray(parsed) || !parsed[0] || typeof parsed[0] !== "object") return null;
    const v = parsed[0] as Record<string, unknown>;
    return {
      facts_id: typeof v.facts_id === "string" ? v.facts_id : "",
      public_slug: typeof v.public_slug === "string" ? v.public_slug : null,
      store_slug: typeof v.store_slug === "string" ? v.store_slug : "",
      target_date: typeof v.target_date === "string" ? v.target_date : "",
    };
  } catch {
    return null;
  }
}
