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
  const url =
    `${endpoint}?select=facts_id,store_slug,target_date,mdx_content,source,updated_at,created_at,error_message` +
    `&source=eq.github_actions_cron&error_message=is.null&mdx_content=not.eq.` +
    `&order=updated_at.desc.nullslast,created_at.desc&limit=${capped}`;
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
        updated_at: typeof v.updated_at === "string" ? v.updated_at : undefined,
        created_at: typeof v.created_at === "string" ? v.created_at : undefined,
      }))
      .filter((v) => v.facts_id && v.store_slug && v.mdx_content);
  } catch {
    return [];
  }
}

export async function fetchAutoBlogDraftByFactsId(factsId: string): Promise<AutoBlogDraftView | null> {
  const conf = endpointUrl();
  if (!conf || !factsId.trim()) return null;
  const { endpoint, key } = conf;
  const url =
    `${endpoint}?select=facts_id,store_slug,target_date,mdx_content,source,updated_at,created_at,error_message` +
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
      updated_at: typeof v.updated_at === "string" ? v.updated_at : undefined,
      created_at: typeof v.created_at === "string" ? v.created_at : undefined,
    };
    return row.facts_id && row.store_slug && row.mdx_content ? row : null;
  } catch {
    return null;
  }
}
