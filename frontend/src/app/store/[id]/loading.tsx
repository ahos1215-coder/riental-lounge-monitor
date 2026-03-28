export default function StoreDetailLoading() {
  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-10">
      <div className="mb-6 h-5 w-24 animate-pulse rounded bg-slate-700/60" />
      <div className="mb-4 h-8 w-64 animate-pulse rounded bg-slate-700/60" />
      <div className="mb-8 h-4 w-40 animate-pulse rounded bg-slate-800/60" />
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="h-24 animate-pulse rounded-2xl bg-slate-800/60" />
        <div className="h-24 animate-pulse rounded-2xl bg-slate-800/60" />
      </div>
      <div className="mt-6 h-64 animate-pulse rounded-2xl bg-slate-800/60" />
      <div className="mt-6 h-40 animate-pulse rounded-2xl bg-slate-800/60" />
    </main>
  );
}
