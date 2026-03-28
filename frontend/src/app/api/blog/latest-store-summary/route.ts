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

function extractSummary(mdx: string): { bullets: string[]; peakHint?: string; avoidHint?: string } {
  const body = stripFrontmatter(mdx);
  const concl = pickSectionLines(body, "今日の結論", 4);
  const times = pickSectionLines(body, "混みやすい時間 / 避けたい時間", 4);

  const bullets: string[] = [];
  if (concl[0]) bullets.push(concl[0]);
  // 「ピーク」「避けたい」を拾えれば優先して入れる（なければ次の結論行）
  const peak = concl.find((s) => s.includes("ピーク"));
  const avoid = concl.find((s) => s.includes("避け"));
  if (peak) bullets.push(peak);
  else if (concl[1]) bullets.push(concl[1]);

  if (avoid) bullets.push(avoid);
  else if (times[0]) bullets.push(times[0]);
  else if (concl[2]) bullets.push(concl[2]);
  if (bullets.length < 3) {
    const extra = pickFirstNonEmptyLine(body);
    if (extra) bullets.push(extra);
  }

  return {
    bullets: bullets.slice(0, 3),
    peakHint: peak,
    avoidHint: avoid,
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
  const updatedLabel = formatUpdatedLabel(row.created_at, row.target_date);
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

