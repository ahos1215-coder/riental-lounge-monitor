/**
 * Weekly Report 関連の共有型定義。
 *
 * v2 redesign (2026-05) で `WeeklyStoreCharts.tsx` が役割を終えたため、
 * そこから `TopWindowChart` 型のみを切り出してここに集約した。
 * 他に Weekly Report 固有の型を増やす場合もこのファイルに追加する。
 */

/** Good Window 区間 (`top_windows[i]`)。/reports/weekly ページの「賑わいやすい時間帯」カード用 */
export type TopWindowChart = {
  start?: string;
  end?: string;
  duration_minutes?: number;
  avg_score?: number;
};
