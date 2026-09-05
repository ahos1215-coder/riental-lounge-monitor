import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { startExposureWatch } from "./useExposureOnce";

/**
 * 露出計測の「配線」の検問（2026-09-06）。
 *
 * 既存テスト（src/lib/analytics.test.ts）は純粋関数 shouldFireExposure しか覆っておらず、
 * IntersectionObserver に何を渡しているかは無検証だった。そのため threshold を渡し忘れて
 * 既定の [0] になり、「画面下からじわじわ入ってくる普通のスクロールでは二度と発火しない」
 * というバグが本番まで素通りした。ここで factory への引数と時間軸の振る舞いを固定する。
 */

type ObserverCall = {
  callback: IntersectionObserverCallback;
  options?: IntersectionObserverInit;
};

/** IntersectionObserver のモック。factory に渡された引数を記録し、通知を手で流し込めるようにする。 */
function createMockObserver() {
  const calls: ObserverCall[] = [];
  const observed: Element[] = [];
  let disconnectCount = 0;

  const factory = (callback: IntersectionObserverCallback, options?: IntersectionObserverInit) => {
    calls.push({ callback, options });
    return {
      observe: (el: Element) => {
        observed.push(el);
      },
      disconnect: () => {
        disconnectCount += 1;
      },
    };
  };

  /** ブラウザからの交差通知を1件流す。ratio>0 なら isIntersecting=true（実ブラウザの挙動に合わせる）。 */
  const emit = (intersectionRatio: number, isIntersecting = intersectionRatio > 0) => {
    const entry = { intersectionRatio, isIntersecting } as IntersectionObserverEntry;
    const call = calls[calls.length - 1];
    call.callback([entry], null as unknown as IntersectionObserver);
  };

  return {
    factory,
    calls,
    observed,
    emit,
    get disconnectCount() {
      return disconnectCount;
    },
  };
}

/** 実 DOM の無い node 環境なので、observe に渡せる最小の Element 代役を作る。 */
const fakeElement = {} as Element;

describe("startExposureWatch — IntersectionObserver への配線", () => {
  it("factory の第2引数に threshold を渡し、その中に 0.5 が含まれる", () => {
    const mock = createMockObserver();

    startExposureWatch({ element: fakeElement, factory: mock.factory, onExpose: () => {} });

    expect(mock.calls).toHaveLength(1);
    const options = mock.calls[0].options;
    // 第2引数そのものが無い＝threshold 既定 [0] に落ちる、というのが直したバグ。
    expect(options).toBeDefined();
    const threshold = options?.threshold;
    expect(Array.isArray(threshold)).toBe(true);
    // 定数から読まずに 0.5 をベタ書きするのは、定数側が壊れてもテストが素通りしないようにするため。
    expect(threshold as number[]).toContain(0.5);
    // 画面外へ出た通知でタイマーを解除する分岐を生かすため 0 も必要。
    expect(threshold as number[]).toContain(0);
  });

  it("observe に渡した要素を監視し、解除関数で disconnect する", () => {
    const mock = createMockObserver();

    const stop = startExposureWatch({
      element: fakeElement,
      factory: mock.factory,
      onExpose: () => {},
    });

    expect(mock.observed).toEqual([fakeElement]);
    expect(mock.disconnectCount).toBe(0);
    stop();
    expect(mock.disconnectCount).toBe(1);
  });
});

describe("startExposureWatch — 発火条件（50%以上が1000ms継続、1回きり）", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("ratio 0.16 の通知だけでは、いくら時間が経っても発火しない", () => {
    const mock = createMockObserver();
    const onExpose = vi.fn();

    startExposureWatch({ element: fakeElement, factory: mock.factory, onExpose });
    mock.emit(0.16);
    vi.advanceTimersByTime(60_000);

    expect(onExpose).not.toHaveBeenCalled();
  });

  it("ratio 0.6 が 1000ms 続いたら1回だけ発火し、observer を切る", () => {
    const mock = createMockObserver();
    const onExpose = vi.fn();

    startExposureWatch({ element: fakeElement, factory: mock.factory, onExpose });
    mock.emit(0.6);

    // 1000ms 未満では鳴らない（「一瞬よぎっただけ」を露出と数えない）。
    vi.advanceTimersByTime(999);
    expect(onExpose).not.toHaveBeenCalled();

    vi.advanceTimersByTime(1);
    expect(onExpose).toHaveBeenCalledTimes(1);
    expect(mock.disconnectCount).toBe(1);

    // その後さらに通知が来ても2回目は無い（1回きりの保証）。
    mock.emit(0.9);
    vi.advanceTimersByTime(60_000);
    expect(onExpose).toHaveBeenCalledTimes(1);
  });

  it("1000ms 経つ前に50%を割り込んだらタイマーが解除され、発火しない", () => {
    const mock = createMockObserver();
    const onExpose = vi.fn();

    startExposureWatch({ element: fakeElement, factory: mock.factory, onExpose });
    mock.emit(0.6);
    vi.advanceTimersByTime(500);
    mock.emit(0.2); // スクロールで半分未満まで隠れた
    vi.advanceTimersByTime(60_000);

    expect(onExpose).not.toHaveBeenCalled();
  });

  it("画面外へ出た後に戻ってきたら、そこから1000ms 計り直して発火する", () => {
    const mock = createMockObserver();
    const onExpose = vi.fn();

    startExposureWatch({ element: fakeElement, factory: mock.factory, onExpose });
    mock.emit(0.6);
    vi.advanceTimersByTime(500);
    mock.emit(0, false); // 完全に画面外
    vi.advanceTimersByTime(500);
    expect(onExpose).not.toHaveBeenCalled();

    mock.emit(0.8); // 戻ってきた
    vi.advanceTimersByTime(1000);
    expect(onExpose).toHaveBeenCalledTimes(1);
  });

  // 名前を実態に合わせた（2026-09-06）。旧名は「解除後に遅れて通知が来ても発火しない」だったが、
  // stop() のあとに emit を流していないので、実際に確かめているのは「stop() が保留中タイマーを
  // 解除する」ことだけだった。stop() 後に emit を流すケースを足さないのは、startExposureWatch に
  // stopped フラグが無く、流せば新しいタイマーが張られて発火してしまう＝テストを通すために実装を
  // 変える必要が出るため。実ブラウザでは disconnect() 後にコールバックが来ないので実害は無く
  // （この点は旧実装から変わっていない）、実装を触らずテスト名を実態に寄せるほうを選んだ。
  it("解除関数は保留中のタイマーを止める（1000ms 到達前のアンマウントで発火しない）", () => {
    const mock = createMockObserver();
    const onExpose = vi.fn();

    const stop = startExposureWatch({ element: fakeElement, factory: mock.factory, onExpose });
    mock.emit(0.6);
    vi.advanceTimersByTime(500);
    stop();
    vi.advanceTimersByTime(60_000);

    expect(onExpose).not.toHaveBeenCalled();
  });

  it("発火済みフラグが立っていれば observer を作らない（effect 再実行での二重計測を防ぐ）", () => {
    const mock = createMockObserver();
    const onExpose = vi.fn();

    startExposureWatch({
      element: fakeElement,
      factory: mock.factory,
      onExpose,
      firedFlag: { current: true },
    });

    expect(mock.calls).toHaveLength(0);
    expect(onExpose).not.toHaveBeenCalled();
  });
});
