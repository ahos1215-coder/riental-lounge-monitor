// MEGRIBI PREVIEW v1 layout
// このコンポーネントの見た目を今後のダッシュボード標準として扱う。
// 見た目を大きく変えるときは、必ず設計を確認してから変更すること。

"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  Area,
  CartesianGrid,
  Legend,
  Line,
  ComposedChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

type StoreId = "ol_nagasaki" | "ol_shibuya" | "ol_fukuoka";

type CongestionLevel = "空いている" | "やや混み" | "混んでいる";

type TimeSeriesPoint = {
  label: string; // 19:00 〜 05:00 の時間ラベル
  menActual: number;
  womenActual: number;
  menForecast: number;
  womenForecast: number;
};

type StoreSnapshot = {
  name: string;
  area: string;
  level: CongestionLevel;
  nowTotal: number;
  nowMen: number;
  nowWomen: number;
  peakTimeLabel: string;
  peakTotal: number;
  recommendation: string;
  series: TimeSeriesPoint[]; // 19:00–05:00 実測 + 予測
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
      "1 時間後にかけて伸びそう。終電前〜終電直後が一番動きやすいタイミング。",
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

// 近くのお店
type PlaceCategory = "karaoke" | "darts" | "lovehotel" | "ramen" | "bar";

type NearbyPlace = {
  id: string;
  name: string;
  category: PlaceCategory;
  distanceMin: number; // 徒歩分
  isOpen: boolean;
  hoursLabel: string; // 例: "18:00〜05:00"
  closingRank: number; // 閉店が遅い順ソート用（大きいほど遅い）
  rating: number;
  reviews: number;
  extra?: {
    vacancy?: string; // ラブホ用
    price?: string; // ラブホ用
    ramenStyle?: string; // ラーメン用
  };
};

const NEARBY_PLACES: NearbyPlace[] = [
  {
    id: "k1",
    name: "カラオケ スカイサイド長崎",
    category: "karaoke",
    distanceMin: 3,
    isOpen: true,
    hoursLabel: "18:00〜05:00",
    closingRank: 29,
    rating: 4.1,
    reviews: 96,
  },
  {
    id: "k2",
    name: "カラオケ ミッドナイト浜町",
    category: "karaoke",
    distanceMin: 6,
    isOpen: true,
    hoursLabel: "19:00〜03:00",
    closingRank: 27,
    rating: 3.9,
    reviews: 54,
  },
  {
    id: "d1",
    name: "ダーツバー Orbit",
    category: "darts",
    distanceMin: 4,
    isOpen: true,
    hoursLabel: "20:00〜04:00",
    closingRank: 28,
    rating: 4.3,
    reviews: 71,
  },
  {
    id: "d2",
    name: "ダーツ＆ビリヤード Vector",
    category: "darts",
    distanceMin: 9,
    isOpen: false,
    hoursLabel: "17:00〜24:00",
    closingRank: 24,
    rating: 4.0,
    reviews: 39,
  },
  {
    id: "l1",
    name: "ホテル ベイサイド",
    category: "lovehotel",
    distanceMin: 7,
    isOpen: true,
    hoursLabel: "チェックイン 20:00〜 / 〜12:00",
    closingRank: 36,
    rating: 4.2,
    reviews: 128,
    extra: {
      vacancy: "空室 5 / 20",
      price: "¥7,800〜",
    },
  },
  {
    id: "l2",
    name: "ホテル コーストライン",
    category: "lovehotel",
    distanceMin: 11,
    isOpen: true,
    hoursLabel: "チェックイン 19:00〜 / 〜11:00",
    closingRank: 35,
    rating: 4.0,
    reviews: 84,
    extra: {
      vacancy: "空室 2 / 18",
      price: "¥8,500〜",
    },
  },
  {
    id: "r1",
    name: "ラーメン 浜んまち とんこつ",
    category: "ramen",
    distanceMin: 2,
    isOpen: true,
    hoursLabel: "18:00〜02:00",
    closingRank: 26,
    rating: 4.4,
    reviews: 212,
    extra: {
      ramenStyle: "とんこつ",
    },
  },
  {
    id: "r2",
    name: "家系ラーメン 銀灯家",
    category: "ramen",
    distanceMin: 5,
    isOpen: true,
    hoursLabel: "19:00〜05:00",
    closingRank: 29,
    rating: 4.1,
    reviews: 134,
    extra: {
      ramenStyle: "家系",
    },
  },
  {
    id: "b1",
    name: "スタンド 雨宿り",
    category: "bar",
    distanceMin: 4,
    isOpen: true,
    hoursLabel: "18:00〜02:00",
    closingRank: 26,
    rating: 4.6,
    reviews: 89,
  },
  {
    id: "b2",
    name: "BAR 灯",
    category: "bar",
    distanceMin: 8,
    isOpen: false,
    hoursLabel: "19:00〜24:00",
    closingRank: 24,
    rating: 4.8,
    reviews: 41,
  },
];

const PLACE_CATEGORY_LABEL: Record<PlaceCategory, string> = {
  karaoke: "カラオケ",
  darts: "ダーツ",
  lovehotel: "ラブホ",
  ramen: "ラーメン",
  bar: "バー",
};

const PLACE_CATEGORY_ORDER: PlaceCategory[] = [
  "karaoke",
  "darts",
  "lovehotel",
  "ramen",
  "bar",
];

// 全国店舗一覧（サンプル）

type NationalStore = {
  id: string;
  brand: string;
  name: string;
  area: string;
  prefecture: string;
  hours: string;
  storeId?: StoreId; // 実測データに紐づく場合のみ
};

const NATIONAL_STORES: NationalStore[] = [
  {
    id: "ns_nagasaki",
    brand: "ORIENTAL LOUNGE",
    name: "長崎",
    area: "長崎・浜の町",
    prefecture: "長崎県",
    hours: "19:00〜05:00",
    storeId: "ol_nagasaki",
  },
  {
    id: "ns_shibuya",
    brand: "ORIENTAL LOUNGE",
    name: "渋谷",
    area: "渋谷・宇田川町",
    prefecture: "東京都",
    hours: "18:00〜05:00",
    storeId: "ol_shibuya",
  },
  {
    id: "ns_shinjuku",
    brand: "ORIENTAL LOUNGE",
    name: "新宿",
    area: "新宿・歌舞伎町",
    prefecture: "東京都",
    hours: "18:00〜05:00",
    storeId: "ol_shibuya", // ダミー
  },
  {
    id: "ns_umeda",
    brand: "ORIENTAL LOUNGE",
    name: "梅田",
    area: "大阪・梅田",
    prefecture: "大阪府",
    hours: "18:00〜05:00",
    storeId: "ol_fukuoka", // ダミー
  },
  {
    id: "ns_fukuoka",
    brand: "ORIENTAL LOUNGE",
    name: "福岡",
    area: "天神・今泉",
    prefecture: "福岡県",
    hours: "19:00〜05:00",
    storeId: "ol_fukuoka",
  },
];

export default function MeguribiDashboardPreview() {
  const [storeId, setStoreId] = useState<StoreId>("ol_nagasaki");

  const snapshot = useMemo(() => MOCK_STORE_DATA[storeId], [storeId]);

  return (
    <div className="min-h-screen bg-black text-slate-50">
      {/* 上部ナビゲーション（スクロール追従） */}
      <header className="sticky top-0 z-30 border-b border-slate-800 bg-black/95 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center gap-4 px-4 py-3">
          {/* ブランドロゴ */}
          <div className="flex items-center gap-3">
            <div className="relative h-8 w-8">
              <div className="absolute inset-0 rounded-full border border-amber-300/80 bg-amber-500/5 shadow-[0_0_25px_rgba(251,191,36,0.45)]" />
              <div className="absolute right-0 top-1/2 h-2.5 w-2.5 -translate-y-1/2 translate-x-0.5 rounded-full bg-amber-300 shadow-[0_0_18px_rgba(251,191,36,0.9)]" />
            </div>
            <p className="text-sm font-semibold tracking-[0.35em] text-amber-100">
              めぐりび
            </p>
          </div>

          {/* ナビメニュー（PC） */}
          <nav className="ml-4 hidden items-center gap-5 text-sm text-slate-300 md:flex">
            <NavItem>店舗一覧</NavItem>
            <NavItem>ブログ一覧</NavItem>
            <NavItem>マイページ</NavItem>
          </nav>

          {/* 検索バー */}
          <div className="ml-auto flex flex-1 items-center justify-end gap-2">
            <div className="flex max-w-xs flex-1 items-center gap-2 rounded-full border border-slate-700 bg-slate-950 px-3 py-1.5 text-xs text-slate-200">
              <span className="text-slate-500">🔍</span>
              <input
                type="search"
                placeholder="サイト内を検索（店舗・ブログなど）"
                className="w-full bg-transparent text-xs outline-none placeholder:text-slate-500"
              />
            </div>
          </div>
        </div>
      </header>

      {/* メイン */}
      <main className="mx-auto flex max-w-6xl flex-col gap-6 px-4 py-6">
        {/* 現在見ている店舗 + KPI */}
        <section className="space-y-3">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="flex flex-col gap-0.5 text-xs">
              <p className="text-[11px] text-slate-400">今見ている店舗</p>
              <p className="text-sm font-semibold text-slate-100">
                {snapshot.area} / {snapshot.name}
              </p>
              <p className="text-[11px] text-slate-500">
                19:00〜05:00 の推移（実測 &amp; 予測 / 男性・女性）
              </p>
            </div>

            <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2.5 py-1 text-[10px] text-emerald-300 ring-1 ring-emerald-500/40">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
              ダミーデータで表示中
            </span>
          </div>

          {/* KPI 行 */}
          <div className="grid gap-2 text-xs md:grid-cols-5">
            <MetricBox
              label="♂ 男性人数"
              value={`${snapshot.nowMen} 人`}
              tone="male"
            />
            <MetricBox
              label="♀ 女性人数"
              value={`${snapshot.nowWomen} 人`}
              tone="female"
            />
            <MetricBox
              label="男女比 (男:女)"
              value={`${snapshot.nowMen}:${snapshot.nowWomen}`}
            />
            <MetricBox label="混雑度" value={snapshot.level} />
            <MetricBox
              label="おすすめ度"
              value={snapshot.recommendation ? "チャンス！" : "様子見"}
            />
          </div>
        </section>

        {/* グラフ */}
        <section className="rounded-3xl border border-slate-800 bg-black p-3 shadow-[0_18px_60px_rgba(0,0,0,0.85)]">
          <div className="flex items-center justify-between gap-2">
            <p className="text-[11px] uppercase tracking-[0.22em] text-slate-500">
              timeline
            </p>
            <p className="text-[11px] text-slate-500">
              実線 = 実測 / 点線 = 予測（ダミーデータ）
            </p>
          </div>

          <div className="mt-3 h-72 w-full rounded-2xl bg-gradient-to-b from-slate-950 via-black to-black p-3">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart
                data={snapshot.series}
                margin={{ top: 5, right: 10, left: 0, bottom: 0 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                <XAxis
                  dataKey="label"
                  tick={{ fontSize: 10, fill: "#9ca3af" }}
                  stroke="#4b5563"
                />
                <YAxis
                  tick={{ fontSize: 10, fill: "#9ca3af" }}
                  stroke="#4b5563"
                  allowDecimals={false}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#020617",
                    border: "1px solid #1f2937",
                    borderRadius: 8,
                    fontSize: 11,
                  }}
                />
                <Legend
                  wrapperStyle={{ fontSize: 10, color: "#9ca3af" }}
                  iconSize={8}
                />

                {/* 実測値 Area */}
                <Area
                  type="monotone"
                  dataKey="menActual"
                  stroke="none"
                  fill="#38bdf8"
                  fillOpacity={0.24}
                />
                <Area
                  type="monotone"
                  dataKey="womenActual"
                  stroke="none"
                  fill="#f472b6"
                  fillOpacity={0.24}
                />

                {/* 実測線 */}
                <Line
                  type="monotone"
                  dataKey="menActual"
                  name="男性（実測）"
                  stroke="#38bdf8"
                  strokeWidth={2}
                  dot={false}
                  connectNulls
                />
                <Line
                  type="monotone"
                  dataKey="womenActual"
                  name="女性（実測）"
                  stroke="#f472b6"
                  strokeWidth={2}
                  dot={false}
                  connectNulls
                />

                {/* 予測線 */}
                <Line
                  type="monotone"
                  dataKey="menForecast"
                  name="男性（予測）"
                  stroke="#38bdf8"
                  strokeWidth={2}
                  dot={false}
                  strokeDasharray="5 4"
                  connectNulls
                />
                <Line
                  type="monotone"
                  dataKey="womenForecast"
                  name="女性（予測）"
                  stroke="#f472b6"
                  strokeWidth={2}
                  dot={false}
                  strokeDasharray="5 4"
                  connectNulls
                />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </section>

        {/* フィードバック */}
        <section className="rounded-3xl border border-slate-800 bg-slate-950/80 p-3 text-xs">
          <FeedbackPoll storeId={storeId} storeName={snapshot.name} />
        </section>

        {/* 近くのお店 */}
        <section className="rounded-3xl border border-slate-800 bg-slate-950/80 p-3 text-xs">
          <NearbyPlacesSection />
        </section>

        {/* 全国店舗一覧 */}
        <section className="rounded-3xl border border-slate-800 bg-slate-950/80 p-3 text-xs">
          <NationalStoresSection
            activeStoreId={storeId}
            onSelectStore={setStoreId}
          />
        </section>

        <footer className="mt-1 border-t border-slate-900 pt-3 text-[10px] text-slate-500">
          <p>
            実装時のイメージ: この UI コンポーネントを{" "}
            <code className="rounded bg-slate-900 px-1">src/app/page.tsx</code>
            に組み込み、バックエンドの{" "}
            <code className="rounded bg-slate-900 px-1">/api/range</code> や{" "}
            <code className="rounded bg-slate-900 px-1">/api/forecast_next_hour</code>{" "}
            などと接続していきます。
          </p>
        </footer>
      </main>
    </div>
  );
}

/* ------- ヘッダーNav ------- */

type NavItemProps = {
  children: ReactNode;
};

function NavItem({ children }: NavItemProps) {
  return (
    <button
      type="button"
      className="text-xs font-medium text-slate-300 transition hover:text-amber-300"
    >
      {children}
    </button>
  );
}

/* ------- KPI ボックス ------- */

type MetricBoxProps = {
  label: string;
  value: string;
  sub?: string;
  tone?: "male" | "female" | "default";
};

function MetricBox({ label, value, sub, tone = "default" }: MetricBoxProps) {
  const valueColorClass =
    tone === "male"
      ? "text-sky-400"
      : tone === "female"
      ? "text-pink-400"
      : "text-slate-50";

  return (
    <div className="rounded-xl bg-slate-950/90 p-2 ring-1 ring-slate-800">
      <p className="text-[10px] text-slate-400">{label}</p>
      <p className={`mt-1 text-sm font-semibold ${valueColorClass}`}>{value}</p>
      {sub && <p className="mt-0.5 text-[10px] text-slate-500">{sub}</p>}
    </div>
  );
}

/* ------- フィードバック ------- */

type FeedbackPollProps = {
  storeId: StoreId;
  storeName: string;
};

type FeedbackOptionId = "success" | "no_success" | "useful" | "useless";

type FeedbackCounts = Record<FeedbackOptionId, number>;

const FEEDBACK_OPTIONS: { id: FeedbackOptionId; label: string }[] = [
  { id: "success", label: "お持ち帰りできた" },
  { id: "no_success", label: "お持ち帰りできなかった" },
  { id: "useful", label: "役に立った" },
  { id: "useless", label: "クソの役にも立たなかった" },
];

function isFeedbackOptionId(value: string): value is FeedbackOptionId {
  return (
    value === "success" ||
    value === "no_success" ||
    value === "useful" ||
    value === "useless"
  );
}

function getTodayFeedbackKeyBase(storeId: StoreId) {
  const today = new Date().toISOString().slice(0, 10); // YYYY-MM-DD
  return `meguribi_feedback_${storeId}_${today}`;
}

function FeedbackPoll({ storeId }: FeedbackPollProps) {
  const [selected, setSelected] = useState<FeedbackOptionId | null>(null);
  const [counts, setCounts] = useState<FeedbackCounts>({
    success: 0,
    no_success: 0,
    useful: 0,
    useless: 0,
  });

  // 当日 + 店舗ごとのローカルストレージから読み込み
  useEffect(() => {
    if (typeof window === "undefined") return;

    const base = getTodayFeedbackKeyBase(storeId);
    const voted = window.localStorage.getItem(base);
    if (voted && isFeedbackOptionId(voted)) {
      setSelected(voted);
    } else {
      setSelected(null);
    }

    const rawCounts = window.localStorage.getItem(`${base}_counts`);
    if (rawCounts) {
      try {
        const parsed = JSON.parse(rawCounts) as Partial<FeedbackCounts>;
        setCounts((prev) => ({ ...prev, ...parsed }));
      } catch {
        // ignore
      }
    } else {
      setCounts({ success: 0, no_success: 0, useful: 0, useless: 0 });
    }
  }, [storeId]);

  const handleClick = (id: FeedbackOptionId) => {
    if (selected) return;

    setSelected(id);
    setCounts((prev) => {
      const next: FeedbackCounts = { ...prev };
      next[id] = (next[id] ?? 0) + 1;

      if (typeof window !== "undefined") {
        const base = getTodayFeedbackKeyBase(storeId);
        window.localStorage.setItem(base, id);
        window.localStorage.setItem(`${base}_counts`, JSON.stringify(next));
      }

      return next;
    });
  };

  const getButtonClasses = (id: FeedbackOptionId, active: boolean) => {
    const base =
      "flex items-center justify-between gap-2 rounded-full border px-3 py-1.5 text-[11px] font-medium transition";
    let color = "";
    if (id === "success") {
      color = active
        ? " border-emerald-400 bg-emerald-500/20 text-emerald-100"
        : " border-emerald-500/60 bg-transparent text-emerald-200 hover:bg-emerald-500/10";
    } else if (id === "no_success") {
      color = active
        ? " border-rose-400 bg-rose-500/20 text-rose-100"
        : " border-rose-500/60 bg-transparent text-rose-200 hover:bg-rose-500/10";
    } else if (id === "useful") {
      color = active
        ? " border-sky-400 bg-sky-500/20 text-sky-100"
        : " border-sky-500/60 bg-transparent text-sky-200 hover:bg-sky-500/10";
    } else {
      color = active
        ? " border-slate-400 bg-slate-500/20 text-slate-100"
        : " border-slate-500/60 bg-transparent text-slate-200 hover:bg-slate-700/30";
    }
    return base + color;
  };

  return (
    <div>
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-semibold text-slate-100">
          フィードバック（簡易集計）
        </p>
        <p className="text-[10px] text-slate-500">
          ※当日 1 回のみ、ブラウザに保存（店舗別）
        </p>
      </div>

      <div className="mt-2 grid gap-2 md:grid-cols-4">
        {FEEDBACK_OPTIONS.map((opt) => {
          const active = selected === opt.id;
          return (
            <button
              key={opt.id}
              type="button"
              onClick={() => handleClick(opt.id)}
              disabled={!!selected && !active}
              className={getButtonClasses(opt.id, active)}
            >
              <span>{opt.label}</span>
              <span className="text-[11px] font-semibold text-slate-50">
                {counts[opt.id] ?? 0}
              </span>
            </button>
          );
        })}
      </div>

      {selected && (
        <p className="mt-2 text-[11px] text-emerald-300">
          フィードバックありがとうございます。予測ビューの改善のヒントとして活用していきます。
        </p>
      )}
    </div>
  );
}

/* ------- 近くのお店 ------- */

type NearbyPlacesSectionProps = {};

type SortMode = "distance" | "closing";

type CategoryLimitMap = Record<PlaceCategory, number>;

function NearbyPlacesSection(_props: NearbyPlacesSectionProps) {
  const [sortMode, setSortMode] = useState<SortMode>("distance");
  const [visibleCount, setVisibleCount] = useState(6);
  const [categoryLimits, setCategoryLimits] = useState<CategoryLimitMap>({
    karaoke: 3,
    darts: 3,
    lovehotel: 3,
    ramen: 3,
    bar: 3,
  });

  const openPlaces = useMemo(() => NEARBY_PLACES.filter((p) => p.isOpen), []);

  const sortedPlaces = useMemo(() => {
    const arr = [...openPlaces];
    if (sortMode === "distance") {
      arr.sort((a, b) => a.distanceMin - b.distanceMin);
    } else {
      arr.sort((a, b) => b.closingRank - a.closingRank);
    }
    return arr;
  }, [openPlaces, sortMode]);

  const limitedPlaces = useMemo(() => {
    const grouped: Record<PlaceCategory, NearbyPlace[]> = {
      karaoke: [],
      darts: [],
      lovehotel: [],
      ramen: [],
      bar: [],
    };

    sortedPlaces.forEach((p) => {
      grouped[p.category].push(p);
    });

    const flattened: NearbyPlace[] = [];
    PLACE_CATEGORY_ORDER.forEach((cat) => {
      const limit = categoryLimits[cat] ?? 0;
      const list = grouped[cat] ?? [];
      list.slice(0, limit).forEach((p) => flattened.push(p));
    });

    return flattened;
  }, [sortedPlaces, categoryLimits]);

  const visiblePlaces = limitedPlaces.slice(0, visibleCount);
  const canLoadMore = visibleCount < limitedPlaces.length;

  const handleCategoryLimitChange = (cat: PlaceCategory, value: string) => {
    const num = Number(value);
    if (Number.isNaN(num) || num < 0) return;
    setCategoryLimits((prev) => ({ ...prev, [cat]: num }));
  };

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-xs font-semibold text-slate-100">
            近くのお店（現在営業中のみ・サンプル）
          </p>
          <p className="mt-0.5 text-[11px] text-slate-400">
            実装時には現在時刻と営業情報をもとに、自動で絞り込む想定です。
          </p>
        </div>

        <div className="flex items-center gap-2 text-[11px] text-slate-300">
          <span className="text-slate-400">並び順</span>
          <div className="flex items-center gap-1 rounded-full bg-slate-900 p-1">
            <button
              type="button"
              onClick={() => setSortMode("distance")}
              className={`rounded-full px-2 py-0.5 ${
                sortMode === "distance"
                  ? "bg-slate-100 text-slate-900"
                  : "text-slate-300"
              }`}
            >
              距離が近い順
            </button>
            <button
              type="button"
              onClick={() => setSortMode("closing")}
              className={`rounded-full px-2 py-0.5 ${
                sortMode === "closing"
                  ? "bg-slate-100 text-slate-900"
                  : "text-slate-300"
              }`}
            >
              閉店が遅い順
            </button>
          </div>
        </div>
      </div>

      {/* カテゴリ別の上限入力 */}
      <div className="mt-3 flex flex-wrap items-center gap-3 text-[10px] text-slate-300">
        <span className="text-slate-400">カテゴリごとの最大件数</span>
        {PLACE_CATEGORY_ORDER.map((cat) => (
          <label key={cat} className="inline-flex items-center gap-1">
            <span>{PLACE_CATEGORY_LABEL[cat]}</span>
            <input
              type="number"
              min={0}
              className="w-12 rounded border border-slate-700 bg-slate-950 px-1 py-0.5 text-[10px] text-slate-50 outline-none"
              value={categoryLimits[cat] ?? 0}
              onChange={(e) => handleCategoryLimitChange(cat, e.target.value)}
            />
          </label>
        ))}
      </div>

      {/* 一覧 */}
      <div className="mt-3 space-y-2">
        {visiblePlaces.map((place) => (
          <div
            key={place.id}
            className="flex flex-col gap-1 rounded-2xl border border-slate-800 bg-slate-950/90 p-2.5 text-[11px] text-slate-100 md:flex-row md:items-center md:justify-between"
          >
            <div className="flex-1">
              <div className="flex flex-wrap items-center gap-1">
                <span className="text-[11px] font-semibold text-slate-50">
                  {place.name}
                </span>
                <span className="rounded-full bg-slate-900 px-2 py-0.5 text-[10px] text-slate-300">
                  {PLACE_CATEGORY_LABEL[place.category]}
                </span>
                <span className="rounded-full bg-emerald-500/10 px-2 py-0.5 text-[10px] text-emerald-300">
                  営業中
                </span>
              </div>

              <div className="mt-1 flex flex-wrap items-center gap-2 text-[10px] text-slate-300">
                <span>徒歩 {place.distanceMin} 分</span>
                <span>営業時間: {place.hoursLabel}</span>
                <span className="flex items-center gap-0.5">
                  <span className="text-amber-300">★</span>
                  <span>
                    {place.rating.toFixed(1)} ({place.reviews})
                  </span>
                </span>
              </div>

              {place.category === "lovehotel" && place.extra && (
                <div className="mt-1 flex flex-wrap items-center gap-2 text-[10px] text-slate-300">
                  {place.extra.vacancy && <span>空室: {place.extra.vacancy}</span>}
                  {place.extra.price && <span>料金: {place.extra.price}</span>}
                </div>
              )}

              {place.category === "ramen" && place.extra?.ramenStyle && (
                <div className="mt-1 text-[10px] text-slate-300">
                  系統: {place.extra.ramenStyle}
                </div>
              )}
            </div>
          </div>
        ))}

        {visiblePlaces.length === 0 && (
          <p className="text-[11px] text-slate-500">
            現在営業中のお店はサンプルデータ上はありません。
          </p>
        )}
      </div>

      {canLoadMore && (
        <div className="mt-3 flex justify-center">
          <button
            type="button"
            onClick={() => setVisibleCount((prev) => prev + 6)}
            className="rounded-full border border-slate-700 bg-slate-900 px-4 py-1.5 text-[11px] font-medium text-slate-100 hover:border-amber-400 hover:text-amber-200"
          >
            もっと見る（+6）
          </button>
        </div>
      )}
    </div>
  );
}

/* ------- 全国店舗一覧 ------- */

type NationalStoresSectionProps = {
  activeStoreId: StoreId;
  onSelectStore: (id: StoreId) => void;
};

function NationalStoresSection({
  activeStoreId,
  onSelectStore,
}: NationalStoresSectionProps) {
  const [keyword, setKeyword] = useState("");

  const filteredStores = useMemo(() => {
    const kw = keyword.trim();
    if (!kw) return NATIONAL_STORES;
    const lower = kw.toLowerCase();
    return NATIONAL_STORES.filter((store) => {
      const haystack = `${store.brand} ${store.name} ${store.area} ${store.prefecture}`.toLowerCase();
      return haystack.includes(lower);
    });
  }, [keyword]);

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs font-semibold text-slate-100">店舗一覧（プレビュー）</p>
        <p className="text-[10px] text-slate-500">
          ※静的サンプル。本番では Supabase の stores テーブルから取得予定。
        </p>
      </div>

      <div className="mt-3 flex max-w-xs items-center gap-2 rounded-full border border-slate-700 bg-slate-950 px-3 py-1.5 text-xs text-slate-200">
        <span className="text-slate-500">🔍</span>
        <input
          type="search"
          placeholder="店舗名・エリアで検索（例: 長崎, 新宿）"
          className="w-full bg-transparent text-xs outline-none placeholder:text-slate-500"
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
        />
      </div>

      <div className="mt-3 grid gap-2 sm:grid-cols-2 md:grid-cols-3">
        {filteredStores.map((store) => {
          const snapshot = store.storeId
            ? MOCK_STORE_DATA[store.storeId]
            : undefined;
          const isActive = store.storeId === activeStoreId;

          return (
            <button
              key={store.id}
              type="button"
              onClick={() => {
                if (store.storeId) {
                  onSelectStore(store.storeId);
                }
              }}
              className={`flex flex-col items-center justify-center rounded-2xl border px-4 py-3 text-center text-slate-100 transition ${
                isActive
                  ? "border-amber-400/80 bg-slate-900 shadow-[0_0_25px_rgba(251,191,36,0.35)]"
                  : "border-slate-800 bg-slate-950/80 hover:border-amber-400/80 hover:bg-slate-900"
              }`}
            >
              <p className="text-[10px] tracking-[0.25em] text-slate-500">
                {store.brand}
              </p>
              <p className="mt-1 text-sm font-semibold text-slate-50">
                {store.name}
              </p>
              <p className="mt-0.5 text-[10px] text-slate-400">{store.area}</p>
              <p className="mt-0.5 text-[10px] text-slate-500">
                {store.prefecture}
              </p>

              {snapshot && (
                <p className="mt-1 text-[10px]">
                  <span className="mr-2 text-sky-400">
                    ♂ {snapshot.nowMen}人
                  </span>
                  <span className="text-pink-400">
                    ♀ {snapshot.nowWomen}人
                  </span>
                </p>
              )}
            </button>
          );
        })}

        {filteredStores.length === 0 && (
          <p className="col-span-full text-[11px] text-slate-500">
            該当する店舗が見つかりませんでした。
          </p>
        )}
      </div>
    </div>
  );
}
