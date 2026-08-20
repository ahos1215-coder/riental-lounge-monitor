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
    //
    // セキュリティヘッダー（診断④ 2026-08-20・W-2）: ログイン機構の無いサイトだが、
    // iframe 埋め込み(クリックジャッキング)と MIME スニッフィングを転ばぬ先の杖として遮断。
    // Cache-Control はここでは絶対に設定しない（上記の二重定義事故の再発防止）。
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Frame-Options", value: "SAMEORIGIN" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        ],
      },
    ];
  },
};

export default nextConfig;
