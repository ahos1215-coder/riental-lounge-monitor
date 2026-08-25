import { useSecondVenues, type SecondVenue } from "../app/hooks/useSecondVenues";
import { track } from "@/lib/analytics";

type SecondVenuesListProps = {
  storeSlug: string;
};

// destination_domain は4リンクとも Google マップ検索 URL のホスト名（www.google.com）で
// 固定になるが、official_site_click と同じパラメータ形にして計測側の扱いを揃えるため渡す。
function destinationDomainOf(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return "";
  }
}

/**
 * second_venue_click の GA4 パラメータを組み立てる純粋関数（テスト容易化のため export）。
 * 2026-08-26 計測レビュー対応: venue_kind は link.purpose をそのまま渡す
 * （"darts"|"karaoke"|"ramen"|"love_hotel"。指示書の想定値 "hotel" は実際の型
 * SecondVenuePurpose に存在しないため、既存の正本の値を使う。詳細は完了報告の
 * 「仕様から外れた点」を参照）。
 */
export function secondVenueClickParams(
  storeSlug: string,
  link: SecondVenue,
): { store_slug: string; venue_kind: SecondVenue["purpose"]; destination_domain: string } {
  return {
    store_slug: storeSlug,
    venue_kind: link.purpose,
    destination_domain: destinationDomainOf(link.url),
  };
}

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
            onClick={() => track("second_venue_click", secondVenueClickParams(storeSlug, link))}
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
