export default function MypageLoading() {
  return (
    <main className="mx-auto w-full max-w-4xl px-4 py-10">
      <div className="mb-6 h-8 w-40 animate-pulse rounded bg-slate-700/60" />
      <div className="mb-4 h-5 w-56 animate-pulse rounded bg-slate-800/60" />
      <div className="grid gap-4 sm:grid-cols-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-44 animate-pulse rounded-2xl bg-slate-800/60" />
        ))}
      </div>
      <div className="mt-8 h-5 w-32 animate-pulse rounded bg-slate-700/60" />
      <div className="mt-3 flex flex-wrap gap-2">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="h-7 w-20 animate-pulse rounded-full bg-slate-800/60" />
        ))}
      </div>
    </main>
  );
}
