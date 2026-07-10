export function StorePageFallback() {
  return (
    <div className="mx-auto w-full max-w-6xl space-y-8 px-4 py-8">
      <div className="space-y-3">
        <div className="h-5 w-48 animate-pulse rounded bg-slate-700/80" />
        <div className="h-40 w-full animate-pulse rounded-2xl bg-slate-800/80" />
        <div className="h-72 w-full animate-pulse rounded-2xl bg-slate-800/80" />
      </div>
      <div className="space-y-3">
        <div className="h-4 w-40 animate-pulse rounded bg-slate-700/80" />
        <div className="grid gap-3 md:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <div
              key={i}
              className="h-44 animate-pulse rounded-2xl border border-slate-800/80 bg-slate-900/60"
            />
          ))}
        </div>
      </div>
    </div>
  );
}
