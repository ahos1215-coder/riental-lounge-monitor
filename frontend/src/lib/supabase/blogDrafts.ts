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
  updated_at?: string;
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

/** Supabase REST の共通ヘッダ。read は取得系、write は PATCH/POST（返り値に行を要求する）用。 */
function restHeaders(key: string, kind: "read" | "write"): Record<string, string> {
  const base = { apikey: key, Authorization: `Bearer ${key}` };
  return kind === "read"
    ? { ...base, Accept: "application/json" }
    : { ...base, "Content-Type": "application/json", Prefer: "return=representation" };
}

/**
 * Supabase REST の GET を1箇所に集約する。URL の組み立て（＝クエリ契約）は各関数に残す。
 *
 * 返り値は「オブジェクトの行だけを残した配列」。取得できなかった場合（HTTP エラー・
 * JSON が配列でない・ネットワーク例外）は null を返し、呼び出し側が null / [] に倒す。
 * 既定は cache:"no-store"（読み手が常に最新を要求する）。一覧系だけ revalidateSeconds を渡す。
 */
async function restGetRows(
  url: string,
  key: string,
  { revalidateSeconds }: { revalidateSeconds?: number } = {},
): Promise<Record<string, unknown>[] | null> {
  try {
    const res = await fetch(url, {
      method: "GET",
      ...(revalidateSeconds === undefined
        ? { cache: "no-store" as const }
        : { next: { revalidate: revalidateSeconds } }),
      headers: restHeaders(key, "read"),
    });
    if (!res.ok) return null;
    const parsed = (await res.json()) as unknown;
    if (!Array.isArray(parsed)) return null;
    return parsed.filter((v): v is Record<string, unknown> => Boolean(v && typeof v === "object"));
  } catch {
    return null;
  }
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
      headers: restHeaders(key, "write"),
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
      headers: restHeaders(key, "write"),
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
    `${endpoint}?select=facts_id,store_slug,target_date,mdx_content,insight_json,source,content_type,edition,public_slug,created_at,updated_at` +
    `&store_slug=eq.${encodeURIComponent(slug)}` +
    `&content_type=eq.${encodeURIComponent(contentType)}` +
    `&is_published=eq.true&error_message=is.null` +
    // 「最後に更新された」レポートを表示する。daily は evening_preview / late_update の
    // 2 edition があり facts_id が異なる別行になる。created_at.desc だと「後から先に作られた
    // edition」が固定で勝ち、直近に再生成した edition(例: 手動再実行や 18:00→21:30 の進行)が
    // 表示されない不整合が起きる(表示の「更新」時刻は updated_at を使うため二重に不整合)。
    // updated_at.desc(nulls last) + created_at.desc をタイブレークにして最新の再生成を出す。
    //
    // target_date.desc を最優先に置くのは carry-over 対策(2026-08-19 監査・所見1)。
    // 生成に失敗した edition は「前回の良品の本文と target_date」をそのまま書き戻す
    // (scripts/local_report_job.py の _apply_carry_over_or_fail) ため、行は古い日付のまま
    // updated_at だけが今になる。updated_at だけで並べると、今日成功した片方の edition より
    // 昨日分の carry-over 行が勝ってしまう。日付が新しい行を先に見る。
    `&order=target_date.desc,updated_at.desc.nullslast,created_at.desc&limit=1`;
  const rows = await restGetRows(url, key);
  const v = rows?.[0];
  if (!v) return null;
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
    updated_at: typeof v.updated_at === "string" ? v.updated_at : undefined,
  };
  return row.facts_id && row.store_slug ? row : null;
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
  const rows = await restGetRows(url, key);
  const v = rows?.[0];
  if (!v) return null;
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
}

export type PublishedEditorialListItem = {
  public_slug: string;
  target_date: string;
};

/**
 * sitemap 用: 公開済み editorial 記事の public_slug 一覧を取得する。
 * 失敗時は空配列を返す（sitemap 生成を壊さない）。
 */
export async function fetchAllPublishedEditorialSlugs(limit = 200): Promise<PublishedEditorialListItem[]> {
  const conf = endpointUrl();
  if (!conf) return [];
  const { endpoint, key } = conf;
  const url =
    `${endpoint}?select=public_slug,target_date` +
    `&content_type=eq.editorial&is_published=eq.true&error_message=is.null` +
    `&public_slug=not.is.null` +
    `&order=created_at.desc&limit=${Math.min(limit, 500)}`;
  const rows = await restGetRows(url, key);
  if (!rows) return [];
  return rows
    .map((v) => ({
      public_slug: typeof v.public_slug === "string" ? v.public_slug : "",
      target_date: typeof v.target_date === "string" ? v.target_date : "",
    }))
    .filter((v) => v.public_slug);
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
      headers: restHeaders(key, "write"),
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
      headers: restHeaders(key, "write"),
      body: JSON.stringify({ is_published: true }),
    });
    const txt = await res.text();
    if (!res.ok) return { ok: false, error: `supabase patch ${res.status}: ${txt.slice(0, 300)}` };
    return { ok: true, publicSlug };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

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
  // 一覧ページは 300 秒キャッシュ（他の GET は no-store）。
  const rows = await restGetRows(url, key, { revalidateSeconds: 300 });
  if (!rows) return [];
  const seen = new Set<string>();
  const items: ReportListItem[] = [];
  for (const v of rows) {
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
}

/**
 * LINE 承認フロー: 特定 LINE ユーザーの最新 editorial 未公開下書きを取得する。
 * "公開" メッセージ受信時に、どの下書きを承認するか特定するために使う。
 */
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
  const rows = await restGetRows(url, key);
  const v = rows?.[0];
  if (!v) return null;
  return {
    facts_id: typeof v.facts_id === "string" ? v.facts_id : "",
    public_slug: typeof v.public_slug === "string" ? v.public_slug : null,
    store_slug: typeof v.store_slug === "string" ? v.store_slug : "",
    target_date: typeof v.target_date === "string" ? v.target_date : "",
  };
}
