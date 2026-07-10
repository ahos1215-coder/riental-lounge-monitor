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
};

export type RelatedRealtimeMap = Record<string, RelatedRealtimeEntry>;
