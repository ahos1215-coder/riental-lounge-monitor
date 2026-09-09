// frontend/src/app/stores/storeCardUnavailable.ts
//
// /stores のカード state に「この店の実測が取れなかった」を反映する純粋関数。
//
// stores-list-client.tsx の markCardUnavailable の中身をここへ出しているのは、
// クライアントコンポーネント本体（React / next/navigation を引き込む .tsx）を
// vitest の node 環境から import せずに、この分岐だけを検問できるようにするため。

import type { StoreRealtimeCard } from "./stores-list-client";

/**
 * その店の実測が取得できなかったときの state 更新。
 *
 * 2 つの状況を**区別する**のがこの関数の役目:
 *
 * 1. まだ良品カードが無い店（stats 未設定）
 *    → dataUnavailable:true の空カードにする。StoreCard の hasStats が false になり、
 *      人数は 1 つも描画されず「混雑データを取得できていません」と出る。
 *      2026-09-09 の Supabase 402 事故で全 42 店が「男性0 / 女性0 / 計0」と出た経路を塞ぐ。
 *
 * 2. **既に人数を出せている良品カードがある店（stats あり）**
 *    → **上書きしない**。呼び出し元は単発 fetch の失敗や例外（一瞬の回線断・JSON 不正）
 *      からもここへ来るため、丸ごと空カードに差し替えると、SSR スナップショットで
 *      正しく出ていたカードが裏側更新中の一瞬の失敗だけで「取得できていません」に化ける。
 *      stats・sparkline・latestActualTs も一緒に捨てられるのでフォールバック表示も効かない。
 *      障害時だけの話ではなく平常時の退行なので、既存の表示をそのまま残す。
 *      鮮度は latestActualTs（StoreCard の「最終 HH:MM 時点」ラベル）が担保する。
 *
 * 2 の場合、この店は今回の取得が打ち切られて予測の続きが来ないため、
 * forecastPending だけは下ろして「取得中」の表示で止まらないようにする
 * （予測が失敗したときの既存の分岐と同じ扱い）。変更が無いときは prev をそのまま返し、
 * React の再レンダーを起こさない。
 */
export function withCardUnavailable(
  prev: Record<string, StoreRealtimeCard>,
  slug: string,
): Record<string, StoreRealtimeCard> {
  const cur = prev[slug];

  if (cur?.stats) {
    if (!cur.forecastPending) return prev;
    return { ...prev, [slug]: { ...cur, forecastPending: false } };
  }

  return {
    ...prev,
    [slug]: {
      slug,
      sparkline: [],
      sparklineMen: [],
      sparklineWomen: [],
      forecastPending: false,
      dataUnavailable: true,
      megribiScore: cur?.megribiScore ?? null,
    },
  };
}
