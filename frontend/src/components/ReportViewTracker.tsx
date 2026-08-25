"use client";

import { useEffect } from "react";
import { sendEvent } from "@/lib/analytics";

/**
 * Fires a report_view GA4 event. Embeddable in server component pages.
 * 2026-08-26 計測レビュー対応: report_read → report_view に改名（mount 時に発火する実態は
 * 「読了」ではなく「開いた」であるため、名前を実態に合わせた。Python週報側
 * scripts/analytics_weekly_report.py は互換のため report_read も引き続き拾う設定なので、
 * 送信側はこの新名称のみでよい）。
 */
export function ReportViewTracker({
  storeSlug,
  reportType,
}: {
  storeSlug: string;
  reportType: "daily" | "weekly";
}) {
  useEffect(() => {
    sendEvent("report_view", { store_slug: storeSlug, report_type: reportType });
  }, [storeSlug, reportType]);

  return null;
}
