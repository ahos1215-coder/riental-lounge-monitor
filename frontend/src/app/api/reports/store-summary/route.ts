"use server";

import { NextResponse } from "next/server";
import {
  fetchLatestPublishedReportByStore,
  isBlogDraftsConfigured,
} from "@/lib/supabase/blogDrafts";

function stripFrontmatter(raw: string): string {
  if (!raw.startsWith("---\n")) return raw;
  const end = raw.indexOf("\n---\n", 4);
  if (end < 0) return raw;
  return raw.slice(end + 5).trimStart();
}

/** MDX 本文から箇条書き（- で始まる行）を最大 max 件抽出 */
function extractBullets(mdx: string, max = 3): string[] {
  const body = stripFrontmatter(mdx);
  const bullets: string[] = [];
  for (const line of body.split("\n")) {
    const trimmed = line.trim();
    if (trimmed.startsWith("- ") || trimmed.startsWith("* ")) {
      const text = trimmed.replace(/^[-*]\s+/, "").trim();
      if (text.length > 0) bullets.push(text);
    }
    if (bullets.length >= max) break;
  }
  return bullets;
}

/** MDX 本文から最初の見出し（## or ###）を抽出 */
function extractFirstHeading(mdx: string): string | null {
  const body = stripFrontmatter(mdx);
  for (const line of body.split("\n")) {
    const m = line.match(/^#{1,3}\s+(.+)/);
    if (m) return m[1].trim();
  }
  return null;
}

function formatJstLabel(iso: string | undefined): string {
  if (!iso) return "—";
  try {
    return new Intl.DateTimeFormat("ja-JP", {
      timeZone: "Asia/Tokyo",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

const EDITION_LABELS: Record<string, string> = {
  evening_preview: "18:00 便",
  late_update: "21:30 便",
  weekly: "週報",
};

export async function GET(req: Request) {
  const url = new URL(req.url);
  const store = (url.searchParams.get("store") ?? "").trim().toLowerCase();

  if (!store) {
    return NextResponse.json({ ok: false, error: "store is required" }, { status: 400 });
  }

  if (!isBlogDraftsConfigured()) {
    return NextResponse.json({ ok: true, daily: null, weekly: null }, { status: 200 });
  }

  const [dailyRow, weeklyRow] = await Promise.all([
    fetchLatestPublishedReportByStore(store, "daily"),
    fetchLatestPublishedReportByStore(store, "weekly"),
  ]);

  const daily = dailyRow
    ? {
        bullets: extractBullets(dailyRow.mdx_content, 3),
        heading: extractFirstHeading(dailyRow.mdx_content),
        updatedAt: formatJstLabel(dailyRow.created_at),
        targetDate: dailyRow.target_date ?? "—",
        editionLabel: EDITION_LABELS[dailyRow.edition ?? ""] ?? dailyRow.edition ?? "",
      }
    : null;

  const weekly = weeklyRow
    ? {
        bullets: extractBullets(weeklyRow.mdx_content, 3),
        heading: extractFirstHeading(weeklyRow.mdx_content),
        updatedAt: formatJstLabel(weeklyRow.created_at),
        targetDate: weeklyRow.target_date ?? "—",
      }
    : null;

  return NextResponse.json({ ok: true, daily, weekly }, { status: 200 });
}
