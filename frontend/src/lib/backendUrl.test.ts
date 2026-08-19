// frontend/src/lib/backendUrl.test.ts
//
// C-13（BACKEND_URL の既定値・別名フォールバックの一本化）の番犬テスト。
//
// 集約前は既定値が経路によって "http://localhost:5000"（12ファイル）と
// "http://127.0.0.1:5000"（LINE/cron の2ファイル）に割れており、`BACKEND-URL` という
// 別名の保険も後者にしか無かった。ここで「1つの決まり方」を固定する。
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { getBackendBaseUrl, isBackendUrlFromEnv } from "./backendUrl";

const KEYS = ["BACKEND_URL", "BACKEND-URL"] as const;
let saved: Record<string, string | undefined> = {};

beforeEach(() => {
  saved = {};
  for (const k of KEYS) {
    saved[k] = process.env[k];
    delete process.env[k];
  }
});

afterEach(() => {
  for (const k of KEYS) {
    if (saved[k] === undefined) delete process.env[k];
    else process.env[k] = saved[k];
  }
});

describe("getBackendBaseUrl", () => {
  it("env 未設定なら既定値（ローカル開発用）", () => {
    expect(getBackendBaseUrl()).toBe("http://localhost:5000");
  });

  it("BACKEND_URL が設定されていればそれを使う", () => {
    process.env.BACKEND_URL = "https://api.example.com";
    expect(getBackendBaseUrl()).toBe("https://api.example.com");
  });

  it("BACKEND-URL（Vercel で別名登録された場合の保険）だけでも拾う", () => {
    process.env["BACKEND-URL"] = "https://alias.example.com";
    expect(getBackendBaseUrl()).toBe("https://alias.example.com");
  });

  it("両方あるときは BACKEND_URL が優先される", () => {
    process.env.BACKEND_URL = "https://primary.example.com";
    process.env["BACKEND-URL"] = "https://alias.example.com";
    expect(getBackendBaseUrl()).toBe("https://primary.example.com");
  });

  it("末尾スラッシュは（何本あっても）除去される", () => {
    process.env.BACKEND_URL = "https://api.example.com/";
    expect(getBackendBaseUrl()).toBe("https://api.example.com");
    process.env.BACKEND_URL = "https://api.example.com///";
    expect(getBackendBaseUrl()).toBe("https://api.example.com");
  });

  it("空文字が設定されていたら空文字のまま（集約前の `??` と同じ扱い）", () => {
    process.env.BACKEND_URL = "";
    expect(getBackendBaseUrl()).toBe("");
  });
});

describe("isBackendUrlFromEnv（LINE webhook の開発時診断ログ backendUrlIsFallback 用）", () => {
  it("env 未設定＝既定値で動いている → false（＝backendUrlIsFallback は true）", () => {
    expect(isBackendUrlFromEnv()).toBe(false);
  });

  it("BACKEND_URL 設定済み → true（＝backendUrlIsFallback は false）", () => {
    process.env.BACKEND_URL = "https://api.example.com";
    expect(isBackendUrlFromEnv()).toBe(true);
  });

  it("BACKEND-URL 別名だけでも設定済みとみなす", () => {
    process.env["BACKEND-URL"] = "https://alias.example.com";
    expect(isBackendUrlFromEnv()).toBe(true);
  });

  it("既定値のリテラル一致に依存しない（旧実装は 127.0.0.1 との文字列比較だった）", () => {
    // 旧実装は既定値を localhost に統一した時点で常に false になってしまう判定だった。
    // 現行は「env の有無」を見るので、既定値の文字列を変えても意味が保たれる。
    process.env.BACKEND_URL = "http://localhost:5000";
    expect(isBackendUrlFromEnv()).toBe(true);
    delete process.env.BACKEND_URL;
    expect(isBackendUrlFromEnv()).toBe(false);
  });
});
