"use client";

import { useEffect } from "react";
import { sendEvent } from "@/lib/analytics";

/** Fires a report_read GA4 event. Embeddable in server component pages. */
export function ReportViewTracker({
  storeSlug,
  reportType,
}: {
  storeSlug: string;
  reportType: "daily" | "weekly";
}) {
  useEffect(() => {
    sendEvent("report_read", { store_slug: storeSlug, report_type: reportType });
  }, [storeSlug, reportType]);

  return null;
}
