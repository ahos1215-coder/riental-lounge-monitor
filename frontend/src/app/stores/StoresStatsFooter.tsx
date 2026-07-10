"use client";

type StoresStatsFooterProps = {
  registeredCount: number;
  regionCount: number;
  areaExamples: string;
};

export function StoresStatsFooter({
  registeredCount,
  regionCount,
  areaExamples,
}: StoresStatsFooterProps) {
  return (
          <section className="grid gap-3 pb-10 md:grid-cols-3">
            <div className="rounded-2xl border border-slate-800 bg-slate-950/80 p-3 text-xs">
              <p className="text-[11px] text-slate-400">登録店舗数</p>
              <p className="mt-1 text-2xl font-semibold text-slate-50">
                {registeredCount}
              </p>
            </div>
            <div className="rounded-2xl border border-slate-800 bg-slate-950/80 p-3 text-xs">
              <p className="text-[11px] text-slate-400">
                カバーする大エリア数（region）
              </p>
              <p className="mt-1 text-2xl font-semibold text-slate-50">
                {regionCount}
              </p>
              <p className="mt-1 text-[10px] text-slate-500">
                営業中かどうかのリアルタイム表示は未連携です。
              </p>
            </div>
            <div className="rounded-2xl border border-slate-800 bg-slate-950/80 p-3 text-xs">
              <p className="text-[11px] text-slate-400">
                掲載エリアの例（先頭3店）
              </p>
              <p className="mt-1 text-base font-semibold leading-snug text-slate-50">
                {areaExamples}
              </p>
            </div>
          </section>
  );
}
