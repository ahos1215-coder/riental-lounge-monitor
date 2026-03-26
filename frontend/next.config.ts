import path from "node:path";
import { loadEnvConfig } from "@next/env";
import type { NextConfig } from "next";

// `.env.local` を親（リポジトリルート）と cwd（frontend）の両方から読む（CRON_SECRET 等がどちらにあっても拾える）
const repoRoot = path.resolve(process.cwd(), "..");
loadEnvConfig(repoRoot);
loadEnvConfig(process.cwd());

const nextConfig: NextConfig = {
  async headers() {
    return [
      {
        // 実測データ: 60秒CDNキャッシュ
        source: "/api/range",
        headers: [
          { key: "Cache-Control", value: "public, s-maxage=60, stale-while-revalidate=300" },
        ],
      },
      {
        source: "/api/range_multi",
        headers: [
          { key: "Cache-Control", value: "public, s-maxage=60, stale-while-revalidate=300" },
        ],
      },
      {
        // 予測データ: 5分CDNキャッシュ（モデル再計算は15分ごと）
        source: "/api/forecast_today",
        headers: [
          { key: "Cache-Control", value: "public, s-maxage=300, stale-while-revalidate=900" },
        ],
      },
      {
        source: "/api/forecast_next_hour",
        headers: [
          { key: "Cache-Control", value: "public, s-maxage=300, stale-while-revalidate=900" },
        ],
      },
      {
        // AIレポート: 10分CDNキャッシュ（18:00/21:30のみ更新）
        source: "/api/reports/:path*",
        headers: [
          { key: "Cache-Control", value: "public, s-maxage=600, stale-while-revalidate=1800" },
        ],
      },
    ];
  },
};

export default nextConfig;
