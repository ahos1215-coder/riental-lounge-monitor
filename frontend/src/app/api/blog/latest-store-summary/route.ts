"use server";

import { NextResponse } from "next/server";
import { fetchLatestPublishedReportByStoreWithStatus } from "@/lib/supabase/blogDrafts";
import { buildLatestSummaryTitle } from "@/lib/blog/latestSummaryTitle";
import {
  pickFirstNonEmptyLine,
  pickSectionLines,
  stripFrontmatter,
} from "@/lib/blog/mdx";

/** AIレポートは 1日2回更新 (18:00/21:30) — 10分 CDN + 30分 stale（reports/store-summary と同一方針） */
const CACHE_HEADER = "public, s-maxage=600, stale-while-revalidate=1800";

function normalizeStoreSlug(v: string | null): string {
  return (v ?? "").trim().toLowerCase();
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

import { formatJstLabel } from "@/lib/dateFormat";

function formatUpdatedLabel(updatedIso: string | undefined, targetDate: string): string {
  const raw = updatedIso?.trim() || "";
  if (!raw) return targetDate;
  const formatted = formatJstLabel(raw);
  return formatted === "-" ? targetDate : formatted;
}

export async function GET(req: Request) {
  const url = new URL(req.url);
  const store = normalizeStoreSlug(url.searchParams.get("store"));
  if (!store) return NextResponse.json({ ok: false, error: "store is required" }, { status: 400 });

  const { row, failed } = await fetchLatestPublishedReportByStoreWithStatus(store, "daily");

  // 取得できなかったときに hasData:false（＝レポートが無い）と偽らない（F11 と同じ扱い）。
  if (failed) {
    return NextResponse.json(
      { ok: false, error: "reports-unavailable" },
      { status: 503, headers: { "cache-control": "no-store" } },
    );
  }

  if (!row) {
    return NextResponse.json(
      { ok: true, hasData: false },
      { status: 200, headers: { "cache-control": CACHE_HEADER } },
    );
  }

  const href = `/reports/daily/${encodeURIComponent(row.store_slug)}`;
  // 最新行は「前夜のレポート」のこともある。翌日昼に前夜の記述を「今日」と名乗らせない
  // （夜セッション日付とズレていれば「前回（M/D）の傾向まとめ」になる）。
  const title = buildLatestSummaryTitle(row.target_date);
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
      headers: { "cache-control": CACHE_HEADER },
    },
  );
}

