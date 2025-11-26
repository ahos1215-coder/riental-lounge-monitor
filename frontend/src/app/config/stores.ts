export type StoreOption = { value: string; label: string };

// value はバックエンドの resolve_store_identifier で解決できるスラッグ
export const STORE_OPTIONS: StoreOption[] = [
  { value: "nagasaki", label: "長崎" },
  { value: "fukuoka", label: "福岡" },
  { value: "shibuya", label: "渋谷本店" },
];

// クエリ未指定時のデフォルト店舗
export const DEFAULT_STORE = STORE_OPTIONS[0].value;
