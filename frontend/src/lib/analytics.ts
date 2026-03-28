/**
 * GA4 analytics helpers.
 * Measurement ID is read from NEXT_PUBLIC_GA_MEASUREMENT_ID.
 * All calls are no-ops when the ID is missing or in non-browser contexts.
 */

export const GA_MEASUREMENT_ID = process.env.NEXT_PUBLIC_GA_MEASUREMENT_ID ?? "";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function gtag(...args: any[]) {
  if (typeof window === "undefined") return;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (window as any).gtag?.(...args);
}

/** Send a custom GA4 event. */
export function sendEvent(name: string, params?: Record<string, string | number | boolean>) {
  if (!GA_MEASUREMENT_ID) return;
  gtag("event", name, params);
}

/** Track a virtual page view (SPA navigation). */
export function sendPageView(url: string) {
  if (!GA_MEASUREMENT_ID) return;
  gtag("config", GA_MEASUREMENT_ID, { page_path: url });
}
