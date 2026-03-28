"use client";

import Link from "next/link";
import { useEffect } from "react";

export default function MypageError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("[megribi] mypage error:", error);
  }, [error]);

  return (
    <main className="mx-auto w-full max-w-4xl px-4 py-10 text-white">
      <Link
        href="/"
        className="mb-8 inline-flex items-center gap-2 text-sm text-white/60 hover:text-white"
      >
        <span aria-hidden>←</span> トップへ
      </Link>
      <div className="mt-10 rounded-2xl border border-rose-500/20 bg-rose-950/20 p-8 text-center">
        <h1 className="text-lg font-semibold text-white">マイページを読み込めませんでした</h1>
        <p className="mt-2 text-sm text-white/50">
          一時的なエラーです。しばらく経ってから再度お試しください。
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
