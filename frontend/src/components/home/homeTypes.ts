export type HomeBlogTeaser = {
  slug: string;
  title: string;
  categoryLabel: string;
  dateLabel: string;
};

export type HomeRepresentativeStore = {
  slug: string;
  name: string;
  areaLabel: string;
};

export type MegribiScoreItem = {
  slug: string;
  score: number;
  total: number | null;
  men: number | null;
  women: number | null;
  female_ratio: number;
  // 相席屋 (ay_*) のみサーバー側で算出された席の埋まり具合(%)。オリエンタルは null。
  men_seat_pct: number | null;
  women_seat_pct: number | null;
};

/** page.tsx（サーバー側）から渡す初期スナップショットの型。クライアント型と同一形状。 */
export type HomeMegribiScoreItem = MegribiScoreItem;
