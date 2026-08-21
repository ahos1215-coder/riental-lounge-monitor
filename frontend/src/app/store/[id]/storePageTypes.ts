export type ReportSummaryItem = {
  bullets: string[];
  heading: string | null;
  updatedAt: string;
  targetDate: string;
} | null;

export type ReportSummaryData = {
  // Daily カードは v2 で削除済 (LatestForecastSummaryCard の「今日の傾向まとめ」に統合)。
  // ここでは weekly のみ保持する。
  weekly: ReportSummaryItem;
  /**
   * /api/reports/store-summary の取得に失敗したか（外部レビュー F11）。
   * 2026-08-21 に同APIは Supabase 障害時 503 を返すようになったが、受け手側が
   * `if (body.ok)` でしか処理しておらず、失敗時は無言でカードが消えるだけだった
   * （「週報がまだ無い」と区別できない）。true のときは LatestForecastSummaryCard の
   * 失敗時と同じトーンの注記を出す。
   */
  weeklyError: boolean;
};

export type RealtimeCardStats = {
  menCount: number;
  womenCount: number;
  nowTotal: number;
  peakPredTotal: number;
  genderRatio: string;
  crowdLevel?: string;
  recommendLabel?: string;
};

export type RelatedRealtimeEntry = {
  stats: RealtimeCardStats;
  sparkline: number[];
  sparklineMen: number[];
  sparklineWomen: number[];
  /** 表示中の人数の元になった最新実測行の ts。StoreCard の鮮度ラベル（閉店中・最終 HH:MM 時点）に使う。 */
  latestActualTs?: string | null;
};

export type RelatedRealtimeMap = Record<string, RelatedRealtimeEntry>;
