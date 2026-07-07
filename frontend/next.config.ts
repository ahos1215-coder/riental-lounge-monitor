import path from "node:path";
import { loadEnvConfig } from "@next/env";
import type { NextConfig } from "next";

// `.env.local` を親（リポジトリルート）と cwd（frontend）の両方から読む（CRON_SECRET 等がどちらにあっても拾える）
const repoRoot = path.resolve(process.cwd(), "..");
loadEnvConfig(repoRoot);
loadEnvConfig(process.cwd());

const nextConfig: NextConfig = {
  async redirects() {
    return [
      {
        source: "/insights/weekly/:store",
        destination: "/reports/weekly/:store",
        permanent: true,
      },
      {
        source: "/insights/weekly",
        destination: "/reports?tab=weekly",
        permanent: true,
      },
    ];
  },
  async headers() {
    // APIのCache-Controlは各 route.ts の CACHE_HEADER に一元化(二重定義解消 2026-07)。
    // 以前はここで /api/* の Cache-Control を上書きしており、各 route.ts が設定した
    // 値と競合して常に next.config 側が勝っていた（route.ts の意図が握りつぶされる）。
    // 今後 /api 配下にキャッシュ関連の非Cache-Controlヘッダーが必要になった場合のみ、
    // ここに source ごとのエントリを追加する。
    return [];
  },
};

export default nextConfig;
