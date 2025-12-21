export type BlogCategoryId =
  | "all"
  | "guide"
  | "beginner"
  | "prediction"
  | "column"
  | "interview";

export type BlogSortId = "all" | "popular" | "latest";

export type BlogPost = {
  slug: string;
  title: string;
  description: string;
  date: string; // YYYY-MM-DD
  categoryId: Exclude<BlogCategoryId, "all">;
  categoryLabel: string;
  badgeClassName: string;
  heroClassName: string;
  views: number; // ダミー人気指標
  minutes: number; // 目安読了時間
  body: string[];
};

export const BLOG_CATEGORIES: Array<{ id: BlogCategoryId; label: string }> = [
  { id: "all", label: "すべて" },
  { id: "guide", label: "使い方ガイド" },
  { id: "beginner", label: "初心者向け" },
  { id: "prediction", label: "予測の仕組み" },
  { id: "column", label: "コラム" },
  { id: "interview", label: "インタビュー" },
];

export const BLOG_SORTS: Array<{ id: BlogSortId; label: string }> = [
  { id: "all", label: "ALL" },
  { id: "popular", label: "人気順" },
  { id: "latest", label: "新着順" },
];

export const BLOG_POSTS: BlogPost[] = [
  {
    slug: "how-to-use-prediction",
    title: "予測の賢い使い方：迷いを減らす3ステップ",
    description:
      "めぐりびの予測を「当てる」より「役立てる」ために。伸び方・ピーク・鈍り方の読み方を整理します。",
    date: "2025-12-05",
    categoryId: "column",
    categoryLabel: "コラム",
    badgeClassName: "bg-violet-600",
    heroClassName: "bg-gradient-to-br from-violet-600/40 via-slate-900 to-black",
    views: 12430,
    minutes: 6,
    body: [
      "予測は未来を断定するためではなく、判断材料を増やして迷いを減らすための道具です。",
      "見るポイントは、(1) 伸び方（増加の勢い）(2) ピーク（山の位置）(3) 鈍り方（落ち始め）です。",
      "まずは数回分、同じ店の「増え方」を追って、自分の行動に効く指標に絞るのがおすすめです。",
    ],
  },
  {
    slug: "beginner-complete-guide",
    title: "初心者必見！相席ラウンジ完全ガイド",
    description:
      "入店から退店までの流れ、料金、マナー、やりがちな失敗まで。最初の一夜で迷わないためのまとめです。",
    date: "2025-11-28",
    categoryId: "beginner",
    categoryLabel: "初心者向け",
    badgeClassName: "bg-pink-600",
    heroClassName: "bg-gradient-to-br from-pink-600/35 via-slate-900 to-black",
    views: 9820,
    minutes: 8,
    body: [
      "最初は料金や流れが不安になりがちですが、手順を知るだけで難易度は大きく下がります。",
      "大事なのは、目的を決めることと、長居しすぎないこと。混雑日は回転が速いのでメリハリが効きます。",
      "最後に、店舗ページで見られる男女比・混雑度の読み方も合わせて押さえると失敗しにくいです。",
    ],
  },
  {
    slug: "women-safety-tips",
    title: "女性向け：安全に楽しむための5つのコツ",
    description:
      "安心して楽しむために。合流の条件、飲み物、連絡先の渡し方、帰宅動線などの基本を整理します。",
    date: "2025-11-25",
    categoryId: "beginner",
    categoryLabel: "初心者向け",
    badgeClassName: "bg-pink-600",
    heroClassName: "bg-gradient-to-br from-pink-600/25 via-slate-900 to-black",
    views: 8120,
    minutes: 7,
    body: [
      "安心して楽しむためには、事前に決めるべきことをルール化しておくのが強いです。",
      "合流の条件、お酒のペース、連絡先の渡し方、帰宅手段を先に決めるだけで負担が減ります。",
      "違和感があるときは無理をせず、席替えや退店を選べる状態にしておくのが基本です。",
    ],
  },
  {
    slug: "prediction-how-it-works",
    title: "予測の仕組み：どんなデータを見ているの？",
    description:
      "めぐりびの予測は、過去の推移と当日の勢いを組み合わせて「次の動き」を推定します。考え方をざっくり解説。",
    date: "2025-11-22",
    categoryId: "prediction",
    categoryLabel: "予測の仕組み",
    badgeClassName: "bg-emerald-600",
    heroClassName: "bg-gradient-to-br from-emerald-600/30 via-slate-900 to-black",
    views: 6440,
    minutes: 5,
    body: [
      "予測は魔法ではなく、似た条件の日を探して次の推移をなぞるイメージに近いです。",
      "データが少ない間は、人数そのものより、増え方（傾き）を見て流れを掴むのが有効です。",
      "将来的にログが増えるほど、曜日・天気・イベントの影響も説明できるようにしていきます。",
    ],
  },
  {
    slug: "manager-interview",
    title: "インタビュー：人気ラウンジ店長が語る裏側",
    description:
      "混雑の波、相席が成立しやすい条件、常連がやっていること。現場の目線から、夜の設計を聞きました。",
    date: "2025-11-20",
    categoryId: "interview",
    categoryLabel: "インタビュー",
    badgeClassName: "bg-sky-600",
    heroClassName: "bg-gradient-to-br from-sky-600/35 via-slate-900 to-black",
    views: 5530,
    minutes: 9,
    body: [
      "現場では、最初の30分で空気が決まることが多いそうです。",
      "データと現場感を合わせると「今日は待てば伸びる日」「今日は早めが良い日」の判断がしやすくなります。",
    ],
  },
  {
    slug: "conversation-tips-men",
    title: "男性向け：好印象を与える会話のテンポ",
    description:
      "盛り上げるより、話しやすい空気を作る。質問・共感・深掘りのテンポで印象を整えます。",
    date: "2025-11-18",
    categoryId: "guide",
    categoryLabel: "使い方ガイド",
    badgeClassName: "bg-indigo-600",
    heroClassName: "bg-gradient-to-br from-indigo-600/35 via-slate-900 to-black",
    views: 4310,
    minutes: 6,
    body: [
      "相席は短時間で距離を縮める場なので、話題よりテンポが効きます。",
      "質問は相手が答えやすい範囲に寄せ、共感で繋いでから深掘りすると自然に続きます。",
      "落ち着いて話したいなら、混雑が強すぎない時間帯を選ぶのも手です。",
    ],
  },
];

export function getPostBySlug(slug: string): BlogPost | undefined {
  return BLOG_POSTS.find((p) => p.slug === slug);
}

export function formatYmdToSlash(ymd: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(ymd);
  if (!m) return ymd;
  return `${m[1]}/${m[2]}/${m[3]}`;
}

export function normalizeParam(v: string | string[] | undefined): string | undefined {
  if (typeof v === "string") return v;
  if (Array.isArray(v)) return v[0];
  return undefined;
}

export function isCategoryId(v: string): v is BlogCategoryId {
  return BLOG_CATEGORIES.some((c) => c.id === (v as BlogCategoryId));
}

export function isSortId(v: string): v is BlogSortId {
  return BLOG_SORTS.some((s) => s.id === (v as BlogSortId));
}