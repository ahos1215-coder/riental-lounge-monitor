import { useSecondVenues } from "../app/hooks/useSecondVenues";

type SecondVenuesListProps = {
  storeSlug: string;
};

export default function SecondVenuesList({ storeSlug }: SecondVenuesListProps) {
  const { data, loading, error } = useSecondVenues(storeSlug);

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-xs font-semibold text-slate-100">
            近くの二次会候補（Google マップ検索リンク）
          </p>
          <p className="text-[11px] text-slate-500">
            ダーツ / カラオケ / ラーメン / ラブホテル をワンクリックで検索します。
          </p>
        </div>
        {loading && <span className="text-[10px] text-slate-500">読み込み中…</span>}
        {error && !loading && (
          <span className="text-[10px] text-rose-400">取得に失敗しました: {error}</span>
        )}
      </div>

      <div className="grid gap-2 sm:grid-cols-2">
        {data.map((link) => (
          <a
            key={link.id}
            href={link.url}
            target="_blank"
            rel="noopener noreferrer"
            className="block rounded-2xl border border-slate-800 bg-slate-950/90 px-3 py-2 text-left text-slate-100 shadow-[0_14px_32px_rgba(0,0,0,0.4)] transition hover:border-amber-300/70 hover:bg-slate-900"
          >
            <p className="text-sm font-semibold text-slate-50">{link.label}</p>
            <p className="mt-0.5 text-[11px] text-slate-400">{link.description}</p>
            <p className="mt-2 text-[11px] font-semibold text-amber-200">
              Google マップで開く ↗
            </p>
          </a>
        ))}

        {!loading && !error && data.length === 0 && (
          <p className="text-[11px] text-slate-500">リンクを生成できませんでした。</p>
        )}
      </div>
    </div>
  );
}
