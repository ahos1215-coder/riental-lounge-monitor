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

/** 純粋関数: 露出イベントを発火してよいか。50%以上 かつ 1000ms以上 かつ 未発火、の全てを満たす時のみ true。 */
export function shouldFireExposure(state: ExposureState): boolean {
  if (state.alreadyFired) return false;
  return state.intersectionRatio >= EXPOSURE_THRESHOLD && state.visibleMs >= EXPOSURE_MIN_VISIBLE_MS;
}

type ObserverFactory = (
  callback: IntersectionObserverCallback,
  options?: IntersectionObserverInit,
) => Pick<IntersectionObserver, "observe" | "disconnect">;

/** 実行時の既定 factory。SSR や IntersectionObserver 非対応環境では null（＝graceful no-op）。 */
function defaultObserverFactory(): ObserverFactory | null {
  if (typeof window === "undefined" || typeof window.IntersectionObserver === "undefined") {
    return null;
  }
  return (callback, options) => new IntersectionObserver(callback, options);
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

    let visibleTimer: ReturnType<typeof setTimeout> | null = null;

    const clearTimer = () => {
      if (visibleTimer !== null) {
        clearTimeout(visibleTimer);
        visibleTimer = null;
      }
    };

    const observer = factory((entries) => {
      const entry = entries[0];
      if (!entry || firedRef.current) return;

      if (entry.isIntersecting && entry.intersectionRatio >= EXPOSURE_THRESHOLD) {
        if (visibleTimer === null) {
          visibleTimer = setTimeout(() => {
            visibleTimer = null;
            if (
              shouldFireExposure({
                intersectionRatio: entry.intersectionRatio,
                visibleMs: EXPOSURE_MIN_VISIBLE_MS,
                alreadyFired: firedRef.current,
              })
            ) {
              firedRef.current = true;
              onExposeRef.current();
              observer.disconnect();
            }
          }, EXPOSURE_MIN_VISIBLE_MS);
        }
      } else {
        clearTimer();
      }
    });

    observer.observe(el);

    return () => {
      clearTimer();
      observer.disconnect();
    };
  }, [options?.observerFactory]);

  return ref;
}
