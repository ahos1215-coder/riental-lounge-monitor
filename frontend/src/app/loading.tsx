export default function GlobalLoading() {
  return (
    <main className="flex min-h-[calc(100vh-80px)] flex-col items-center justify-center bg-black">
      <div className="flex items-center gap-2 text-white/40">
        <span
          className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-white/20 border-t-indigo-400"
          aria-hidden
        />
        <span className="text-sm">読み込み中…</span>
      </div>
    </main>
  );
}
