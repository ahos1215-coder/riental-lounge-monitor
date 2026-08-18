import { StoreSsrSummary } from "@/components/store/StoreSsrSummary";
import { buildStoreSsrSummary } from "@/lib/store/ssrSummary";
import type { StoreSnapshot } from "@/app/hooks/useStorePreviewData";

/**
 * /store/[id] の Suspense fallback。
 *
 * この fallback は「静的HTMLに実際に載る唯一のUI」でもある。StorePageInner /
 * MeguribiDashboardPreview が useSearchParams() を使うため、静的プリレンダ時に React が
 * この Suspense 境界を CSR へ bail し、生成される HTML にはこの fallback だけが焼かれる
 * （さらに内側の PreviewMainSection は dynamic(ssr:false)）。
 *
 * そのため initialSnapshot（page.tsx がサーバーで取得済みの実データ）がある場合は、
 * 一番上のスケルトン矩形の代わりに実データのテキスト（StoreSsrSummary）を描画する。
 * ハイドレーション後は本物のダッシュボードに差し替わるため最終的な画面は変わらず、
 * その代わりクローラが読める店舗固有のテキストがHTMLに載る。
 * initialSnapshot が無い（バックエンド不達など）場合は従来どおり全面スケルトン。
 */
export function StorePageFallback({
  initialSnapshot = null,
}: {
  initialSnapshot?: StoreSnapshot | null;
} = {}) {
  const summary = buildStoreSsrSummary(initialSnapshot);
  return (
    <div className="mx-auto w-full max-w-6xl space-y-8 px-4 py-8">
      <div className="space-y-3">
        <div className="h-5 w-48 animate-pulse rounded bg-slate-700/80" />
        {summary ? (
          <StoreSsrSummary data={summary} />
        ) : (
          <div className="h-40 w-full animate-pulse rounded-2xl bg-slate-800/80" />
        )}
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
