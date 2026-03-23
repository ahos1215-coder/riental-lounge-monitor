/**
 * OGP・canonical 用のサイト原点 URL。
 * 本番では `NEXT_PUBLIC_SITE_URL` または `NEXT_PUBLIC_BASE_URL` を推奨（末尾スラッシュなし）。
 */
export function getMetadataBaseUrl(): URL {
  const raw =
    process.env.NEXT_PUBLIC_SITE_URL?.trim() ||
    process.env.NEXT_PUBLIC_BASE_URL?.trim() ||
    (process.env.VERCEL_URL ? `https://${process.env.VERCEL_URL}` : "") ||
    "http://localhost:3000";
  const normalized = raw.replace(/\/+$/, "");
  try {
    return new URL(normalized);
  } catch {
    return new URL("http://localhost:3000");
  }
}
