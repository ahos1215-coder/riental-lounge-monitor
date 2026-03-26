"use client";

import { useEffect } from "react";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("[megribi] page error:", error);
  }, [error]);

  return (
    <main className="flex min-h-[calc(100vh-80px)] flex-col items-center justify-center bg-black px-4 text-white">
      <div className="text-center">
        <p className="text-4xl font-bold text-white/20">500</p>
        <h1 className="mt-3 text-lg font-semibold text-white">
          ページの読み込みに失敗しました
        </h1>
        <p className="mt-2 text-sm text-white/50">
          一時的なエラーです。しばらく経ってから再度お試しください。
        </p>
        {error.digest && (
          <p className="mt-1 font-mono text-xs text-white/25">{error.digest}</p>
        )}
        <button
          type="button"
          onClick={reset}
          className="mt-6 rounded-xl border border-white/10 bg-white/[0.04] px-5 py-2 text-sm text-white/70 transition hover:border-indigo-400/30 hover:text-indigo-200"
        >
          再読み込み
        </button>
      </div>
    </main>
  );
}
