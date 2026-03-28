export default function DailyReportLoading() {
  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-10">
      <div className="mb-6 h-4 w-36 animate-pulse rounded bg-slate-700/60" />
      <div className="mb-2 h-8 w-72 animate-pulse rounded bg-slate-700/60" />
      <div className="mb-8 h-4 w-48 animate-pulse rounded bg-slate-800/60" />
      <div className="space-y-4">
        <div className="h-6 w-full animate-pulse rounded bg-slate-800/60" />
        <div className="h-6 w-5/6 animate-pulse rounded bg-slate-800/60" />
        <div className="h-6 w-4/6 animate-pulse rounded bg-slate-800/60" />
        <div className="h-6 w-full animate-pulse rounded bg-slate-800/60" />
        <div className="h-6 w-3/4 animate-pulse rounded bg-slate-800/60" />
      </div>
    </main>
  );
}
