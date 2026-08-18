import type { StoreSsrSummaryData } from "@/lib/store/ssrSummary";

/**
 * サーバー側HTMLに実データをテキストで出すための、店舗詳細ページ用サマリーカード。
 *
 * 置き場所は StorePageFallback（Suspense の fallback）。/store/[id] は
 * useSearchParams() を使うクライアントツリーのせいで静的プリレンダ時に CSR へ bail するため、
 * 静的HTMLに載るのは fallback だけ ＝ ここが「クローラが読めるテキストを出せる唯一の場所」。
 * ハイドレーション後は本物のダッシュボード（StoreRealtimeStatusCard 等）に差し替わるので、
 * 利用者が最終的に見る画面は変わらない。差し替え前後で見た目が飛ばないよう、
 * StoreRealtimeStatusCard と同じ枠・同じ数値タイポグラフィに揃えている
 * （従来はここが灰色のスケルトン矩形だった）。
 *
 * 値の組み立ては lib/store/ssrSummary.ts の buildStoreSsrSummary（純粋関数）が担当する。
 * 実データが無い場合は同関数が null を返すので、呼び出し側は従来どおりスケルトンを出す
 * （0人・--:-- のような「空箱」を作らない）。
 *
 * 時刻依存の値（「◯分前更新」やピーク進捗）は一切描画しない。ISR で焼かれた HTML では
 * 生成時刻がずれて嘘になるため、最終実測は JST の絶対時刻で出す。
 */
export function StoreSsrSummary({ data }: { data: StoreSsrSummaryData }) {
  const isPercent = data.genderStats.some((s) => s.value.endsWith("%"));

  return (
    <section className="rounded-2xl border border-slate-800 bg-gradient-to-b from-slate-950/95 to-black/90 p-4 shadow-[0_12px_40px_rgba(0,0,0,0.45)] ring-1 ring-white/[0.05]">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div className="min-w-0">
          <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-500">
            リアルタイム
          </p>
          <p className="mt-0.5 truncate text-[11px] text-slate-400">
            {data.areaLabel} / {data.storeName}
          </p>
          {data.occupancyLabel && data.occupancyValue && (
            <p className="mt-0.5 text-[11px] text-slate-400">
              {data.occupancyLabel}{" "}
              <span className="font-semibold text-slate-200">{data.occupancyValue}</span>
            </p>
          )}
        </div>
        {data.updatedText && (
          <p className="mt-0.5 text-[10px] text-slate-500">最終更新 {data.updatedText}</p>
        )}
      </div>

      {data.genderStats.length > 0 && (
        <div className="mt-3">
          {isPercent && (
            <p className="mb-1 text-[11px] font-semibold tracking-wide text-slate-300">
              席の埋まり具合{" "}
              <span className="font-normal text-slate-500">（人数ではありません）</span>
            </p>
          )}
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            {data.genderStats.map((stat, i) => (
              <span key={stat.label} className="inline-flex items-baseline gap-1.5">
                {i > 0 && (
                  <span className="mr-1.5 text-slate-600" aria-hidden>
                    ·
                  </span>
                )}
                <span
                  className={`text-[11px] font-medium ${
                    stat.label === "男性" ? "text-cyan-300/90" : "text-pink-300/90"
                  }`}
                >
                  {stat.label}
                </span>
                <span
                  className={`text-2xl font-black tabular-nums leading-none md:text-3xl ${
                    stat.label === "男性" ? "text-cyan-200" : "text-pink-200"
                  }`}
                >
                  {stat.value}
                </span>
              </span>
            ))}
          </div>
        </div>
      )}

      {data.ratioText && (
        <p className="mt-3 text-[11px] text-slate-400">
          男女比 <span className="font-medium text-slate-200">{data.ratioText}</span>
        </p>
      )}

      {data.peakText && (
        <p className="mt-2 text-[11px] text-slate-400">
          ピーク目安 <span className="font-medium text-slate-200">{data.peakText}</span>
        </p>
      )}

      {data.hourly.length > 0 && (
        <p className="mt-2 text-[11px] leading-relaxed text-slate-400">
          時間帯別の混雑（実測）{" "}
          <span className="text-slate-300">
            {data.hourly.map((h) => `${h.label} ${h.value}`).join(" / ")}
          </span>
        </p>
      )}
    </section>
  );
}
