"use client";

import type { StoreSnapshot } from "../app/hooks/useStorePreviewData";

type StoreStatusMessagesProps = {
  loading?: boolean;
  error?: string | null;
  hasData: boolean;
  forecastStatus: StoreSnapshot["forecastStatus"];
};

export default function StoreStatusMessages({
  loading,
  error,
  hasData,
  forecastStatus,
}: StoreStatusMessagesProps) {
  return (
    <>
      {loading && <p className="text-[10px] text-slate-500">データ取得中…</p>}
      {error && (
        <p className="max-w-[14rem] text-[10px] text-rose-400">
          データ取得に失敗しました（ベース表示中）
        </p>
      )}
      {!loading && !error && !hasData && (
        <p className="max-w-[14rem] text-[10px] text-amber-300">
          データがまだありません。計測待ちか、閉店時間帯の可能性があります。
        </p>
      )}
      {!loading && !error && hasData && forecastStatus === "retrying" && (
        <p className="max-w-[16rem] text-[10px] text-sky-300">
          予測データを再取得しています…
        </p>
      )}
      {!loading && !error && hasData && forecastStatus === "unavailable" && (
        <p className="max-w-[16rem] text-[10px] text-amber-300">
          予測データを取得できませんでした。実測グラフのみ表示しています。
        </p>
      )}
      {!loading && !error && forecastStatus === "insufficient_history" && (
        <p className="max-w-[16rem] text-[10px] text-amber-300">
          データ準備中：履歴が少なく今夜の予測はまだ出せません。実測のみ表示しています。
        </p>
      )}
    </>
  );
}
