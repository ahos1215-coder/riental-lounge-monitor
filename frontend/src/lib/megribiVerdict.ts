/**
 * 「今夜の評決」まわりの共有ロジック・文言。
 *
 * 評決バッジのしきい値(0.65 / 0.40)は StoreCard.tsx の MegribiScoreBadge、
 * compare-client.tsx の scoreLabel と同じもの。表記ゆれ・しきい値のズレを防ぐため、
 * このファイルを唯一の定義元とし、各所から参照する想定（既存2箇所は当面据え置き、
 * 新規のストアページはここを使う）。
 */

/**
 * 現在人数とピーク予測から「混雑度（目安）」の一言を作る。
 * StoreRealtimeStatusCard と TonightVerdictCard の両方から参照し、表記を統一する。
 */
export function crowdHintFromTotals(nowTotal: number, peakTotal: number): string {
  if (peakTotal <= 0) return "予測データ待ち";
  const r = nowTotal / peakTotal;
  if (r >= 0.85) return "混雑に近い目安";
  if (r >= 0.45) return "ほどよい目安";
  return "空いている目安";
}

export type VerdictTone = "good" | "warn" | "neutral";

export type VerdictInfo = {
  tone: VerdictTone;
  label: string;
};

/** めぐりびスコア(0.0〜1.0) → 評決ラベル。しきい値は 0.65 / 0.40（既存バッジと同一）。 */
export function verdictFromScore(score: number | null | undefined): VerdictInfo {
  if (score == null || Number.isNaN(score)) {
    return { tone: "neutral", label: "データ待ち" };
  }
  if (score >= 0.65) return { tone: "good", label: "今が狙い目" };
  if (score >= 0.4) return { tone: "warn", label: "様子見" };
  return { tone: "neutral", label: "今は他店が良いかも" };
}

/** 評決トーンごとの色クラス（バッジ・枠線など）。既存の緑/黄/中立バッジと系統を合わせる。 */
export const VERDICT_TONE_CLASSES: Record<
  VerdictTone,
  { badge: string; border: string; text: string }
> = {
  good: {
    badge: "bg-emerald-500/20 text-emerald-300 ring-1 ring-emerald-500/40",
    border: "border-emerald-500/25",
    text: "text-emerald-300",
  },
  warn: {
    badge: "bg-amber-500/20 text-amber-300 ring-1 ring-amber-500/40",
    border: "border-amber-500/25",
    text: "text-amber-300",
  },
  neutral: {
    badge: "bg-slate-500/20 text-slate-300 ring-1 ring-slate-500/40",
    border: "border-slate-600/30",
    text: "text-slate-300",
  },
};

/**
 * megribi_score の意味づけ注記。スコアを表示する箇所ではこの文言を再利用し、
 * 「なんとなく出てる数字」ではなく根拠のある指標であることを一貫して伝える。
 */
export const MEGRIBI_SCORE_NOTE =
  "席の埋まり具合 × 女性比率から算出。高いほど今夜の相席チャンスが大きい。";

/** 実測データの鮮度がこの分数を超えると「ライブ」ではなく「最終計測」表記に切り替える。 */
export const STALE_DATA_THRESHOLD_MIN = 30;

export type FreshnessInfo = {
  minutesAgo: number;
  /** true: 直近実測（ライブ感を出してよい） / false: 閉店時間帯などで古い（正直に「最終計測」と出す） */
  isFresh: boolean;
  label: string;
};

/** 実測データの ISO タイムスタンプ → 「◯分前更新」等の鮮度ラベル。 */
export function formatFreshness(latestActualTs: string | null | undefined, now: Date = new Date()): FreshnessInfo | null {
  if (!latestActualTs) return null;
  const t = new Date(latestActualTs).getTime();
  if (Number.isNaN(t)) return null;
  const diffMs = now.getTime() - t;
  const minutesAgo = Math.max(0, Math.round(diffMs / 60000));
  const isFresh = minutesAgo <= STALE_DATA_THRESHOLD_MIN;
  const label = isFresh
    ? minutesAgo <= 1
      ? "たった今更新"
      : `${minutesAgo}分前更新`
    : `最終計測 ${minutesAgo}分前`;
  return { minutesAgo, isFresh, label };
}

export type PeakTiming = "future" | "past" | "unknown";

/** ピークの実タイムスタンプ(peakTs)から、まだ先か過ぎたかを判定する。 */
export function peakTimingFromTs(peakTs: string | null | undefined, now: Date = new Date()): PeakTiming {
  if (!peakTs) return "unknown";
  const t = new Date(peakTs).getTime();
  if (Number.isNaN(t)) return "unknown";
  return t >= now.getTime() ? "future" : "past";
}

/** 「動きどき」の一言。ピークが未来なら混む前の行動を促し、過ぎていれば落ち着く旨を伝える。 */
export function movementHint(peakTimeLabel: string, timing: PeakTiming): string | null {
  if (timing === "unknown" || !peakTimeLabel || peakTimeLabel === "--:--") return null;
  if (timing === "future") return `混みきる前の今〜${peakTimeLabel}が動きどき`;
  return "ピークは過ぎ、これから落ち着きます";
}
