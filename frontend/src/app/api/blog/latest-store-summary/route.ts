"use server";

import { NextResponse } from "next/server";
import { fetchLatestPublishedReportByStore, isBlogDraftsConfigured } from "@/lib/supabase/blogDrafts";

function normalizeStoreSlug(v: string | null): string {
  return (v ?? "").trim().toLowerCase();
}

function stripFrontmatter(raw: string): string {
  if (!raw.startsWith("---\n")) return raw;
  const end = raw.indexOf("\n---\n", 4);
  if (end < 0) return raw;
  return raw.slice(end + 5).trimStart();
}

function pickSectionLines(md: string, heading: string, max = 4): string[] {
  const h = `## ${heading}`.trim();
  const idx = md.indexOf(h);
  if (idx < 0) return [];
  const rest = md.slice(idx + h.length);
  const next = rest.search(/\n##\s+/);
  const block = (next >= 0 ? rest.slice(0, next) : rest).trim();
  const lines = block
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean)
    .filter((s) => s.startsWith("- "))
    .map((s) => s.replace(/^-+\s+/, "").trim());
  return lines.slice(0, Math.max(1, max));
}

function pickFirstNonEmptyLine(md: string, maxLen = 120): string | null {
  const line = md
    .split("\n")
    .map((s) => s.trim())
    .find((s) => s && !s.startsWith("#") && !s.startsWith("- "));
  if (!line) return null;
  return line.length > maxLen ? `${line.slice(0, maxLen - 1)}…` : line;
}

function extractSummary(mdx: string): { bullets: string[]; peakHint?: string } {
  const body = stripFrontmatter(mdx);
  const concl = pickSectionLines(body, "今日の結論", 4);

  const bullets: string[] = [];
  for (const line of concl) {
    // avoid_time 由来の行はスキップ（入店のおすすめ / 入店しやすさ 等）
    if (/入店の(おすすめ|しやすさ)|待ちにくさ/.test(line)) continue;
    bullets.push(line);
    if (bullets.length >= 3) break;
  }

  if (bullets.length === 0) {
    const extra = pickFirstNonEmptyLine(body);
    if (extra) bullets.push(extra);
  }

  const peakHint = concl.find((s) => s.includes("ピーク"));

  return {
    bullets: bullets.slice(0, 3),
    peakHint,
  };
}

function formatUpdatedLabel(updatedIso: string | undefined, targetDate: string): string {
  const raw = updatedIso?.trim() || "";
  if (!raw) return targetDate;
  try {
    return new Intl.DateTimeFormat("ja-JP", {
      timeZone: "Asia/Tokyo",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(new Date(raw));
  } catch {
    return targetDate;
  }
}

export async function GET(req: Request) {
  const url = new URL(req.url);
  const store = normalizeStoreSlug(url.searchParams.get("store"));
  if (!store) return NextResponse.json({ ok: false, error: "store is required" }, { status: 400 });

  if (!isBlogDraftsConfigured()) {
    return NextResponse.json({ ok: true, hasData: false }, { status: 200 });
  }

  const row = await fetchLatestPublishedReportByStore(store, "daily");
  if (!row) return NextResponse.json({ ok: true, hasData: false }, { status: 200 });

  const href = `/reports/daily/${encodeURIComponent(row.store_slug)}`;
  const title = `今日の傾向まとめ`;
  const updatedLabel = formatUpdatedLabel(row.updated_at ?? row.created_at, row.target_date);
  const { bullets } = extractSummary(row.mdx_content);

  return NextResponse.json(
    {
      ok: true,
      hasData: true,
      href,
      title,
      updatedLabel,
      bullets,
    },
    {
      status: 200,
      headers: { "cache-control": "public, s-maxage=60, stale-while-revalidate=300" },
    },
  );
}

