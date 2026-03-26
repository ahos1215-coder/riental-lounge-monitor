export default function ReportsLoading() {
  return (
    <main className="mx-auto w-full max-w-6xl px-4 py-8">
      <div className="mb-4 h-8 w-56 animate-pulse rounded bg-slate-700/60" />
      <div className="mb-6 flex gap-2">
        <div className="h-9 w-24 animate-pulse rounded-xl bg-slate-700/60" />
        <div className="h-9 w-24 animate-pulse rounded-xl bg-slate-700/40" />
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 9 }).map((_, i) => (
          <div key={i} className="h-32 animate-pulse rounded-2xl bg-slate-800/60" />
        ))}
      </div>
    </main>
  );
}
