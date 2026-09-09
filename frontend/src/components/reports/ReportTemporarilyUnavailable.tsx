import Link from "next/link";

/**
 * レポート本体は存在するはずなのに、いま取りに行けなかったときの表示。
 *
 * ここで notFound() を返さないのが要点（2026-09-09・Supabase 402 事故）:
 * 404 は CDN に HIT で載るため、復旧後もしばらく「ページが無い」状態が残り、
 * Search Console にクロールエラーが積み上がる。ページの noindex 設定は
 * 各ページの generateMetadata が持っており、ここでは変えない。
 */
export function ReportTemporarilyUnavailable({
  storeLabel,
  storeSlug,
  reportType,
}: {
  storeLabel: string;
  storeSlug: string;
  reportType: "daily" | "weekly";
}) {
  const typeLabel = reportType === "daily" ? "Daily Report" : "Weekly Report";
  const backHref = reportType === "daily" ? "/reports" : "/reports?tab=weekly";

  return (
    <main
      data-report-state="unavailable"
      className="mx-auto w-full max-w-3xl px-4 py-10 text-white"
    >
      <Link
        href={backHref}
        className="mb-8 inline-flex items-center gap-2 text-sm text-white/60 transition hover:text-white"
      >
        <span aria-hidden>←</span> AI予測レポート一覧
      </Link>

      <div className="mt-10 rounded-2xl border border-amber-500/20 bg-amber-950/20 p-8 text-center">
        <h1 className="text-lg font-semibold text-white">
          {storeLabel} {typeLabel}は今だけ表示できません
        </h1>
        <p className="mt-3 text-sm leading-relaxed text-white/60">
          レポートが無くなったわけではなく、データの読み込みに一時的に失敗しています。
          しばらく経ってから再度お試しください。
        </p>
        <div className="mt-6 flex flex-wrap justify-center gap-3">
          <Link
            href={`/store/${storeSlug}`}
            className="rounded-xl border border-white/10 bg-white/[0.04] px-5 py-2 text-sm text-white/70 transition hover:border-indigo-400/30 hover:text-indigo-200"
          >
            店舗ページを見る
          </Link>
          <Link
            href={backHref}
            className="rounded-xl border border-white/10 bg-white/[0.04] px-5 py-2 text-sm text-white/70 transition hover:border-indigo-400/30 hover:text-indigo-200"
          >
            レポート一覧へ
          </Link>
        </div>
      </div>
    </main>
  );
}
