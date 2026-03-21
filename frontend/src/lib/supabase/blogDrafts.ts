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

export async function insertBlogDraft(row: BlogDraftRow): Promise<{ ok: true; id: string } | { ok: false; error: string }> {
  const url = getEnv("SUPABASE_URL");
  const key = serviceRoleKey();
  if (!url || !key) {
    return { ok: false, error: "Supabase env missing (SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY)" };
  }

  const endpoint = `${url.replace(/\/+$/, "")}/rest/v1/blog_drafts`;

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
    const res = await fetch(endpoint, {
      method: "POST",
      headers: {
        apikey: key,
        Authorization: `Bearer ${key}`,
        "Content-Type": "application/json",
        Prefer: "return=representation",
      },
      body: JSON.stringify(body),
    });

    const txt = await res.text();
    if (!res.ok) {
      return { ok: false, error: `supabase ${res.status}: ${txt.slice(0, 500)}` };
    }

    let id = "";
    try {
      const parsed = JSON.parse(txt) as unknown;
      if (Array.isArray(parsed) && parsed[0] && typeof parsed[0] === "object" && parsed[0] !== null) {
        const first = parsed[0] as Record<string, unknown>;
        id = typeof first.id === "string" ? first.id : "";
      }
    } catch {
      /* ignore */
    }

    return { ok: true, id: id || "unknown" };
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    return { ok: false, error: msg };
  }
}
