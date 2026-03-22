import path from "node:path";
import { loadEnvConfig } from "@next/env";
import type { NextConfig } from "next";

// `.env.local` を親（リポジトリルート）と cwd（frontend）の両方から読む（CRON_SECRET 等がどちらにあっても拾える）
const repoRoot = path.resolve(process.cwd(), "..");
loadEnvConfig(repoRoot);
loadEnvConfig(process.cwd());

const nextConfig: NextConfig = {
  /* config options here */
};

export default nextConfig;
