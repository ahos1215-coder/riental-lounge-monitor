export type ForecastPoint = {
  ts: string;
  men_pred: number;
  women_pred: number;
  total_pred: number;
};

export type ForecastResponse = {
  ok: boolean;
  data: ForecastPoint[];
  error?: string;
};
