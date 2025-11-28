"use client";

// MEGRIBI PREVIEW v1 layout
// このコンポーネントの見た目を今後のダッシュボード標準として扱う（見た目を変える場合は要相談）

import { useMemo, useState } from "react";
import PreviewHeader from "./PreviewHeader";
import PreviewMainSection from "./PreviewMainSection";

export type StoreId = "ol_nagasaki" | "ol_shibuya" | "ol_fukuoka";

export type CongestionLevel = "空いている" | "やや混み" | "混んでいる";

export type TimeSeriesPoint = {
  label: string; // 19:00〜05:00 の時間ラベル
  menActual: number;
  womenActual: number;
  menForecast: number;
  womenForecast: number;
};

export type StoreSnapshot = {
  name: string;
  area: string;
  level: CongestionLevel;
  nowTotal: number;
  nowMen: number;
  nowWomen: number;
  peakTimeLabel: string;
  peakTotal: number;
  recommendation: string;
  series: TimeSeriesPoint[]; // 19:00〜05:00 実測 + 予測
};

const MOCK_STORE_DATA: Record<StoreId, StoreSnapshot> = {
  ol_nagasaki: {
    name: "オリエンタルラウンジ 長崎",
    area: "長崎・浜の町",
    level: "やや混み",
    nowTotal: 34,
    nowMen: 20,
    nowWomen: 14,
    peakTimeLabel: "24:00 ごろ",
    peakTotal: 58,
    recommendation:
      "1 時間後にかけて伸びそう。終電前〜終電直後が動きやすいタイミング。",
    series: [
      { label: "19:00", menActual: 6, womenActual: 4, menForecast: 6, womenForecast: 4 },
      { label: "20:00", menActual: 9, womenActual: 7, menForecast: 10, womenForecast: 8 },
      { label: "21:00", menActual: 13, womenActual: 10, menForecast: 14, womenForecast: 11 },
      { label: "22:00", menActual: 16, womenActual: 12, menForecast: 18, womenForecast: 13 },
      { label: "23:00", menActual: 18, womenActual: 13, menForecast: 21, womenForecast: 15 },
      { label: "24:00", menActual: 20, womenActual: 14, menForecast: 24, womenForecast: 17 },
      { label: "25:00", menActual: 18, womenActual: 12, menForecast: 22, womenForecast: 15 },
      { label: "26:00", menActual: 13, womenActual: 9, menForecast: 17, womenForecast: 11 },
      { label: "27:00", menActual: 8, womenActual: 6, menForecast: 10, womenForecast: 8 },
      { label: "28:00", menActual: 4, womenActual: 3, menForecast: 6, womenForecast: 4 },
      { label: "29:00", menActual: 2, womenActual: 2, menForecast: 4, womenForecast: 3 },
      { label: "30:00", menActual: 1, womenActual: 1, menForecast: 3, womenForecast: 2 },
    ],
  },
  ol_shibuya: {
    name: "オリエンタルラウンジ 渋谷",
    area: "渋谷・宇田川町",
    level: "混んでいる",
    nowTotal: 76,
    nowMen: 48,
    nowWomen: 28,
    peakTimeLabel: "23:00 ごろ",
    peakTotal: 92,
    recommendation:
      "かなり賑わい気味。待ち時間は出るが『勢い』を優先したいときに。",
    series: [
      { label: "19:00", menActual: 18, womenActual: 10, menForecast: 18, womenForecast: 10 },
      { label: "20:00", menActual: 24, womenActual: 14, menForecast: 26, womenForecast: 16 },
      { label: "21:00", menActual: 30, womenActual: 20, menForecast: 32, womenForecast: 22 },
      { label: "22:00", menActual: 36, womenActual: 24, menForecast: 40, womenForecast: 27 },
      { label: "23:00", menActual: 40, womenActual: 26, menForecast: 46, womenForecast: 30 },
      { label: "24:00", menActual: 38, womenActual: 24, menForecast: 42, womenForecast: 27 },
      { label: "25:00", menActual: 32, womenActual: 20, menForecast: 36, womenForecast: 23 },
      { label: "26:00", menActual: 24, womenActual: 16, menForecast: 28, womenForecast: 18 },
      { label: "27:00", menActual: 18, womenActual: 12, menForecast: 20, womenForecast: 13 },
      { label: "28:00", menActual: 12, womenActual: 8, menForecast: 14, womenForecast: 9 },
      { label: "29:00", menActual: 6, womenActual: 4, menForecast: 8, womenForecast: 5 },
      { label: "30:00", menActual: 2, womenActual: 2, menForecast: 4, womenForecast: 3 },
    ],
  },
  ol_fukuoka: {
    name: "オリエンタルラウンジ 福岡",
    area: "天神・今泉",
    level: "空いている",
    nowTotal: 18,
    nowMen: 11,
    nowWomen: 7,
    peakTimeLabel: "25:00 ごろ",
    peakTotal: 40,
    recommendation:
      "今はゆったり。深夜帯にかけてじわじわ上がりそうなので、長居前提なら◎。",
    series: [
      { label: "19:00", menActual: 4, womenActual: 2, menForecast: 4, womenForecast: 2 },
      { label: "20:00", menActual: 5, womenActual: 3, menForecast: 6, womenForecast: 4 },
      { label: "21:00", menActual: 7, womenActual: 4, menForecast: 8, womenForecast: 5 },
      { label: "22:00", menActual: 8, womenActual: 5, menForecast: 10, womenForecast: 6 },
      { label: "23:00", menActual: 9, womenActual: 6, menForecast: 12, womenForecast: 8 },
      { label: "24:00", menActual: 11, womenActual: 7, menForecast: 15, womenForecast: 10 },
      { label: "25:00", menActual: 11, womenActual: 7, menForecast: 14, womenForecast: 9 },
      { label: "26:00", menActual: 9, womenActual: 6, menForecast: 12, womenForecast: 8 },
      { label: "27:00", menActual: 7, womenActual: 5, menForecast: 9, womenForecast: 6 },
      { label: "28:00", menActual: 4, womenActual: 3, menForecast: 6, womenForecast: 4 },
      { label: "29:00", menActual: 2, womenActual: 2, menForecast: 4, womenForecast: 3 },
      { label: "30:00", menActual: 1, womenActual: 1, menForecast: 2, womenForecast: 2 },
    ],
  },
};

export default function MeguribiDashboardPreview() {
  const [storeId, setStoreId] = useState<StoreId>("ol_nagasaki");
  const snapshot = useMemo(() => MOCK_STORE_DATA[storeId], [storeId]);

  return (
    <div className="min-h-screen bg-black text-slate-50">
      <PreviewHeader />
      <PreviewMainSection
        storeId={storeId}
        snapshot={snapshot}
        storeDataMap={MOCK_STORE_DATA}
        onSelectStore={setStoreId}
      />
    </div>
  );
}
