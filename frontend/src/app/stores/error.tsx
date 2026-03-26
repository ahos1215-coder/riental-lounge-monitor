"use client";

import { useEffect } from "react";

export default function StoresError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("[megribi] stores error:", error);
  }, [error]);

  return (
    <main className="flex min-h-[calc(100vh-80px)] flex-col items-center justify-center bg-black px-4 text-white">
      <div className="text-center">
        <h1 className="text-lg font-semibold text-white">店舗一覧を読み込めませんでした</h1>
        <p className="mt-2 text-sm text-white/50">
          通信エラーが発生しました。しばらく経ってから再度お試しください。
        </p>
        <button
          type="button"
          onClick={reset}
          className="mt-6 rounded-xl border border-white/10 bg-white/[0.04] px-5 py-2 text-sm text-white/70 transition hover:border-indigo-400/30 hover:text-indigo-200"
        >
          再試行
        </button>
      </div>
    </main>
  );
}
