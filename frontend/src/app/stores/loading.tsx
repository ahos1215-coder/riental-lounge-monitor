export default function StoresLoading() {
  return (
    <main className="mx-auto w-full max-w-6xl px-4 py-8">
      <div className="mb-6 h-7 w-48 animate-pulse rounded bg-slate-700/60" />
      <div className="mb-6 flex gap-2">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="h-8 w-20 animate-pulse rounded-full bg-slate-700/60" />
        ))}
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {Array.from({ length: 12 }).map((_, i) => (
          <div key={i} className="h-40 animate-pulse rounded-2xl bg-slate-800/60" />
        ))}
      </div>
    </main>
  );
}
