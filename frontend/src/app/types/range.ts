export type RangeRow = {
  ts: string;
  men: number | null;
  women: number | null;
  total: number | null;
  store_id?: string;
  src_brand?: string;
  weather_code?: number;
  weather_label?: string;
  temp_c?: number;
  precip_mm?: number;
};

export type RangeResponse = {
  ok: boolean;
  rows: RangeRow[];
  error?: string;
};
