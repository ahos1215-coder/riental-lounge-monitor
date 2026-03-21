import path from "node:path";
import { loadEnvConfig } from "@next/env";
import type { NextConfig } from "next";

// リポジトリルートの `.env.local` を読み込む（`frontend` で `npm run dev` / `build` すると cwd は frontend のため親ディレクトリを指定）
loadEnvConfig(path.resolve(process.cwd(), ".."));

const nextConfig: NextConfig = {
  /* config options here */
};

export default nextConfig;
