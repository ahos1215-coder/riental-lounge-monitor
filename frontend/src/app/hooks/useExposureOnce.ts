"use client";

import { useEffect, useRef } from "react";

/**
 * 送客2面（official_site_click / second_venue_click）の露出計測（2026-08-26 計測レビューR2対応）。
 *
 * レビュー§4-2の部分反論を採用: 広範な `decision_card_view` 群は見送るが、送客クリック2種だけは
 * 露出分母が無いと「表示されていない」のか「表示されたが押されない」のかを区別できない。
 * ここでは判定条件（50%以上の交差率が1000ms以上継続、1回きり）を純粋関数として切り出し、
 * hook 本体はその条件を IntersectionObserver で満たすまで待つだけの薄いラッパーにする。
 */

/** shouldFireExposure が受け取る状態。副作用を持たない純粋関数として単体テストする。 */
export type ExposureState = {
  /** 現在の交差率（0〜1）。 */
  intersectionRatio: number;
  /** 交差率がしきい値を超えたまま継続している時間（ms）。 */
  visibleMs: number;
  /** 既に発火済みか（1回きりを保証するためのガード）。 */
  alreadyFired: boolean;
};

const EXPOSURE_THRESHOLD = 0.5;
const EXPOSURE_MIN_VISIBLE_MS = 1000;

/**
 * IntersectionObserver に渡す threshold（2026-09-06 修正）。
 *
 * なぜ明示が必要か: 以前は factory を第2引数なしで呼んでいたため threshold が既定の `[0]` になり、
 * 「交差率 0 ↔ 0超」を跨いだ瞬間しか通知が来なかった。一方コールバックは 0.5 以上を要求するので、
 * 画面下からじわじわ入ってくる＝人間の普通のスクロールでは ratio がごく小さい1回だけ通知され、
 * その後100%表示のまま何秒経っても二度と発火しない。結果、observe 開始時点で既に画面内にあった
 * 要素しか計測できていなかった。
 *
 * 再現の根拠（2026-09-05 の計測診断。本番 https://www.meguribi.jp/store/shibuya をブラウザで開き、
 * window.IntersectionObserver を計装して「構築時オプション」と「届いたコールバック列」を記録した。
 * この関数を実装したエージェント自身がブラウザで確認したわけではなく、別調査の観測結果を根拠にしている）:
 *   - 二次会リストの observer は構築時オプションが null ＝ threshold は既定の [0] だった。
 *   - scrollY 0 では {isIntersecting:false, ratio:0}、scrollY 760 で {isIntersecting:true, ratio:0.161}。
 *     届いたコールバックはこの ratio:0.161 の1件のみ。
 *   - その後リストが完全表示（ratio 1.0）になり10秒以上経っても追加コールバックはゼロで、
 *     second_venue_view は送信されなかった。
 *   - 対照: /reports/daily/<slug> ではカードが observe 時点で既に画面内だったため ratio:1 が届き、
 *     official_site_view は発火した＝「最初から見えている要素だけ計測できていた」ことの裏付け。
 *
 * 0.5 を入れるのは「50%を跨いだ瞬間」を必ず受け取るため。0 も残すのは、要素が画面外へ出た時に
 * 通知を受けて待機タイマーを解除する既存の else 分岐を確実に生かすため（0 を落とすと、
 * 半分未満まで隠れた後に完全に外へ出る動きが通知されなくなる）。
 *
 * export しないのは、このモジュールの外に読み手が居ないため（テストは定数側が壊れた時に素通り
 * しないよう、意図的に 0 / 0.5 をベタ書きしている）。
 */
const EXPOSURE_OBSERVER_THRESHOLDS: readonly number[] = [0, EXPOSURE_THRESHOLD];

/** 純粋関数: 露出イベントを発火してよいか。50%以上 かつ 1000ms以上 かつ 未発火、の全てを満たす時のみ true。 */
export function shouldFireExposure(state: ExposureState): boolean {
  if (state.alreadyFired) return false;
  return state.intersectionRatio >= EXPOSURE_THRESHOLD && state.visibleMs >= EXPOSURE_MIN_VISIBLE_MS;
}

type ObserverFactory = (
  callback: IntersectionObserverCallback,
  options?: IntersectionObserverInit,
) => Pick<IntersectionObserver, "observe" | "disconnect">;

/** 発火済みフラグ。hook では useRef、テストでは素のオブジェクトを渡す。 */
type FiredFlag = { current: boolean };

/** 実行時の既定 factory。SSR や IntersectionObserver 非対応環境では null（＝graceful no-op）。 */
function defaultObserverFactory(): ObserverFactory | null {
  if (typeof window === "undefined" || typeof window.IntersectionObserver === "undefined") {
    return null;
  }
  return (callback, options) => new IntersectionObserver(callback, options);
}

/**
 * hook 本体から切り出した監視ロジック（React 非依存）。戻り値は監視解除関数。
 *
 * なぜ切り出したか: このリポジトリの vitest は `environment: "node"`（jsdom も testing-library も
 * 無い）ため React hook をレンダーして検証できず、「factory に何を渡しているか」という配線が
 * 丸ごと無検証だった。上記の threshold バグが素通りしたのはこれが原因。React に依存しない関数に
 * しておけばモック factory を直接注入して検問できる（2026-09-06）。
 */
export function startExposureWatch(params: {
  element: Element;
  factory: ObserverFactory;
  onExpose: () => void;
  /** 省略時はこの呼び出し限りのフラグ。hook からは effect をまたいで持続する ref を渡す。 */
  firedFlag?: FiredFlag;
}): () => void {
  const { element, factory, onExpose } = params;
  const fired = params.firedFlag ?? { current: false };
  if (fired.current) return () => {};

  let visibleTimer: ReturnType<typeof setTimeout> | null = null;

  const clearTimer = () => {
    if (visibleTimer !== null) {
      clearTimeout(visibleTimer);
      visibleTimer = null;
    }
  };

  const observer = factory(
    (entries) => {
      const entry = entries[0];
      if (!entry || fired.current) return;

      if (entry.isIntersecting && entry.intersectionRatio >= EXPOSURE_THRESHOLD) {
        if (visibleTimer === null) {
          visibleTimer = setTimeout(() => {
            visibleTimer = null;
            if (
              shouldFireExposure({
                intersectionRatio: entry.intersectionRatio,
                visibleMs: EXPOSURE_MIN_VISIBLE_MS,
                alreadyFired: fired.current,
              })
            ) {
              fired.current = true;
              onExpose();
              observer.disconnect();
            }
          }, EXPOSURE_MIN_VISIBLE_MS);
        }
      } else {
        clearTimer();
      }
    },
    // threshold を渡さないと既定の [0] になって「50%を跨いだ瞬間」の通知が来ない（上の定数コメント参照）。
    { threshold: [...EXPOSURE_OBSERVER_THRESHOLDS] },
  );

  observer.observe(element);

  return () => {
    clearTimer();
    observer.disconnect();
  };
}

/**
 * 要素が画面内に50%以上・1000ms以上表示されたら一度だけ `onExpose` を呼ぶ。
 * `observerFactory` を注入可能にしてあり、テストではモックを渡す（実行時は未指定で
 * window.IntersectionObserver を使う）。IntersectionObserver 非対応環境・SSR では何もしない
 * （エラーにせず静かに発火しないだけ＝画面表示への影響ゼロ）。
 */
export function useExposureOnce<T extends Element>(
  onExpose: () => void,
  options?: { observerFactory?: ObserverFactory | null },
) {
  const ref = useRef<T | null>(null);
  const firedRef = useRef(false);
  const onExposeRef = useRef(onExpose);

  // レンダー中に ref を更新すると React の警告対象になるため、コミット後の effect で同期する
  // （onExpose は呼び出し側で useCallback される想定だが、素の関数でも壊れないようにする）。
  useEffect(() => {
    onExposeRef.current = onExpose;
  }, [onExpose]);

  useEffect(() => {
    const el = ref.current;
    if (!el || firedRef.current) return;

    const factory =
      options?.observerFactory !== undefined ? options.observerFactory : defaultObserverFactory();
    if (!factory) return; // 非対応環境 / SSR: 何もしない（graceful no-op）

    return startExposureWatch({
      element: el,
      factory,
      // 発火時点の最新 onExpose を読むため、ref 越しに呼ぶ（束縛を固定しない）。
      onExpose: () => onExposeRef.current(),
      firedFlag: firedRef,
    });
  }, [options?.observerFactory]);

  return ref;
}
