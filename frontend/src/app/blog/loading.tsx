export default function BlogLoading() {
  return (
    <main className="mx-auto w-full max-w-4xl px-4 py-10">
      <div className="mb-6 h-8 w-32 animate-pulse rounded bg-slate-700/60" />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="h-32 animate-pulse rounded-2xl bg-slate-800/60" />
        ))}
      </div>
    </main>
  );
}
