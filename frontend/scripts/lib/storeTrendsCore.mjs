// 店舗ページ「混みやすい曜日・時間帯」用の週次ヒートマップ集約（純関数・fs なし）。
// content/insights/weekly/<slug>/<YYYY-MM-DD>.json の day_hour_heatmap を直近数週ぶん
// サンプル数で重み付き平均し、1店舗ぶんのエントリにまとめる。LLM 文は一切使わない。

export const TREND_MAX_WEEKS = 4;
/** 同じ週の再実行ファイル（数日差）を重複採用しないための最小間隔（日） */
export const TREND_MIN_GAP_DAYS = 6;
/** 最新ファイルからさかのぼる最大日数 */
export const TREND_WINDOW_DAYS = 35;
/** ヒートマップの時間帯（夜の並び順） */
export const HEATMAP_HOURS = [19, 20, 21, 22, 23, 0, 1, 2, 3, 4];

const FILE_RE = /^\d{4}-\d{2}-\d{2}\.json$/;
const DAY_MS = 24 * 60 * 60 * 1000;
const JST_OFFSET_MS = 9 * 60 * 60 * 1000;

function fileDateMs(name) {
  return Date.parse(`${name.slice(0, 10)}T00:00:00Z`);
}

/** 新しい順に最大4週ぶんのファイル名を選ぶ。 */
export function selectRecentWeekFiles(fileNames) {
  const names = fileNames
    .filter((n) => typeof n === "string" && FILE_RE.test(n) && Number.isFinite(fileDateMs(n)))
    .sort((a, b) => (a < b ? 1 : a > b ? -1 : 0));
  if (names.length === 0) return [];
  const newestMs = fileDateMs(names[0]);
  const accepted = [names[0]];
  let lastMs = newestMs;
  for (let i = 1; i < names.length && accepted.length < TREND_MAX_WEEKS; i++) {
    const ms = fileDateMs(names[i]);
    if (ms > lastMs - TREND_MIN_GAP_DAYS * DAY_MS) continue;
    if (ms < newestMs - TREND_WINDOW_DAYS * DAY_MS) break;
    accepted.push(names[i]);
    lastMs = ms;
  }
  return accepted;
}

/** 複数週の heatmap.cells を (day,hour) ごとにサンプル数重みで平均する。 */
export function mergeWeeklyHeatmaps(docs) {
  const acc = new Map();
  for (const doc of docs) {
    const cells = doc?.day_hour_heatmap?.cells;
    if (!Array.isArray(cells)) continue;
    for (const c of cells) {
      if (!c) continue;
      const { day, hour, avg_occupancy: occ, avg_female_ratio: fem, sample_count: n } = c;
      if (![day, hour, occ, fem, n].every((v) => typeof v === "number" && Number.isFinite(v))) continue;
      if (n <= 0) continue;
      const key = `${day}:${hour}`;
      const cur = acc.get(key) ?? { d: day, h: hour, n: 0, o: 0, f: 0 };
      cur.n += n;
      cur.o += occ * n;
      cur.f += fem * n;
      acc.set(key, cur);
    }
  }
  const hourOrder = (h) => {
    const i = HEATMAP_HOURS.indexOf(h);
    return i < 0 ? 999 : i;
  };
  const round3 = (x) => Math.round(x * 1000) / 1000;
  return [...acc.values()]
    .filter((c) => c.n > 0)
    .sort((a, b) => a.d - b.d || hourOrder(a.h) - hourOrder(b.h) || a.h - b.h)
    .map((c) => ({
      d: c.d,
      h: c.h,
      o: round3(c.o / c.n),
      f: round3(c.f / c.n),
      n: Math.round(c.n),
    }));
}

function pad2(n) {
  return String(n).padStart(2, "0");
}

/** JST（UTC+9）のカレンダー日付 YYYY-MM-DD。offsetMs は追加で引くミリ秒（夜日付用）。 */
function jstDate(ms, minusMs = 0) {
  const d = new Date(ms + JST_OFFSET_MS - minusMs);
  return `${d.getUTCFullYear()}-${pad2(d.getUTCMonth() + 1)}-${pad2(d.getUTCDate())}`;
}

/** 1店舗ぶんのエントリを作る。データが無ければ null。 */
export function buildStoreTrendEntry(fileNames, docs) {
  if (!Array.isArray(docs) || docs.length === 0) return null;
  const cells = mergeWeeklyHeatmaps(docs);
  if (cells.length === 0) return null;
  const starts = docs
    .map((d) => Date.parse(d?.period?.start))
    .filter((x) => Number.isFinite(x));
  const ends = docs
    .map((d) => Date.parse(d?.period?.end))
    .filter((x) => Number.isFinite(x));
  if (starts.length === 0 || ends.length === 0) return null;
  const weeks = fileNames.map((n) => n.slice(0, 10));
  return {
    weeks,
    periodStart: jstDate(Math.min(...starts)),
    // 夜の日付規約: JST の -6 時間でその夜の日付とする（05:59 までは前日の夜）
    periodEnd: jstDate(Math.max(...ends), 6 * 60 * 60 * 1000),
    cells,
  };
}
