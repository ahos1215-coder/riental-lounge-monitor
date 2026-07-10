"use client";

import { useEffect, useState } from "react";

/**
 * コールド店舗（CDN MISS + バックエンド輻輳）での初回表示を守るためのフェッチ延期ゲート。
 * グラフの生命線である range/forecast_today（useStorePreviewData）は絶対に遅延させず、
 * それ以外の非クリティカルな並列フェッチ（関連店舗・レポート要約など）だけを
 * 「メインデータの初回解決（loading=false）」または「フォールバックタイマー」のどちらか
 * 早い方まで遅らせる。initialSnapshot が既にある（ISRスナップショット命中）場合は
 * mainReady が最初のレンダーから true になるため、ほぼ即座に発火する。
 */
export function useDeferredFetchGate(mainReady: boolean, fallbackMs = 2_500): boolean {
  const [timerElapsed, setTimerElapsed] = useState(mainReady);

  useEffect(() => {
    if (mainReady || timerElapsed) return;
    const t = setTimeout(() => setTimerElapsed(true), fallbackMs);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mainReady, fallbackMs]);

  return mainReady || timerElapsed;
}
