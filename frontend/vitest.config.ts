import path from "node:path";
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
      // Next の "server-only" マーカーは node 環境の vitest に実体が無い（src/test/server-only-stub.ts 参照）
      "server-only": path.resolve(__dirname, "./src/test/server-only-stub.ts"),
    },
  },
});
