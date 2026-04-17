import type { MetadataRoute } from "next";
import { getMetadataBaseUrl } from "@/lib/siteUrl";

export default function robots(): MetadataRoute.Robots {
  const base = getMetadataBaseUrl().toString().replace(/\/+$/, "");
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
        disallow: ["/api/", "/mypage"],
      },
    ],
    sitemap: `${base}/sitemap.xml`,
    host: base,
  };
}
