export type BrandFilter = "all" | "oriental" | "jis" | "aisekiya";
export type ForecastPoint = { ts: string; total_pred?: number };

export const BRAND_TABS: { id: BrandFilter; label: string }[] = [
  { id: "all", label: "すべて" },
  { id: "oriental", label: "ORIENTAL LOUNGE" },
  { id: "jis", label: "JIS" },
  { id: "aisekiya", label: "相席屋" },
];

export const STORES_PER_PAGE = 12;

export const toHmJst = (iso: string): string =>
  new Intl.DateTimeFormat("ja-JP", {
    timeZone: "Asia/Tokyo",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(iso));

export const crowdLabelFromPred = (maxPred: number): string => {
  if (maxPred >= 120) return "混雑";
  if (maxPred >= 80) return "ほどよい";
  return "空いている";
};
