// frontend/src/lib/store/crowdThresholds.ts
//
// 「ピーク人数の絶対値で混雑ラベルを決める」閾値の単一ソース。
//
// 経緯: 同じ 120/80 が store 一覧（storesListHelpers.crowdLabelFromPred）と
// LINE 用の下書き（lib/blog/insightFromRange.computeInsight）に別々に手書きされていた。
//
// ★ 既知の弱点（オーナー判断待ち・値はここでは変えない）★
// この絶対人数の閾値は小型店で永遠に「空いている」側に張り付く（lib/featureFlags.ts の
// SHOW_MEGRIBI_JUDGMENTS が false になっている理由の一つ）。表側の一覧はフラグで隠れているが、
// LINE の editorial 文面（crowd_label）には同じ閾値のラベルが今も出ている。
// 直す場合は「店舗ごとの実績（実ピーク/中央値）に対する相対評価」への再設計が要る。
//
// ラベル文言は呼び出し側ごとに違う（一覧: 混雑/ほどよい/空いている、LINE: 混み/ほどよい/空き）ので
// ここでは**数値だけ**を共有する。

/** この人数以上で「最も混んでいる」側のラベル */
export const CROWD_ABS_BUSY_MIN = 120;
/** この人数以上で「ほどよい」ラベル（未満は空き側） */
export const CROWD_ABS_MODERATE_MIN = 80;

/** 3段階のどれかを返す（文言は呼び出し側が決める）。 */
export function crowdTierFromPeakTotal(peakTotal: number): "busy" | "moderate" | "quiet" {
  if (peakTotal >= CROWD_ABS_BUSY_MIN) return "busy";
  if (peakTotal >= CROWD_ABS_MODERATE_MIN) return "moderate";
  return "quiet";
}
