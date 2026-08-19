// frontend/scripts/lib/insightCore.mjs
//
// 「夜窓(19:00-05:00 JST)の実測/予測 → ピーク・空き・混雑ラベル」を出す純粋関数。
//
// ★ 鏡像注意 ★
// このファイルは frontend/src/lib/blog/insightFromRange.ts と**同じ計算**をする双子。
// generate-public-facts.mjs は GHA から `node scripts/generate-public-facts.mjs` で
// 素の node 実行されるため TS を import できず、やむを得ず並行実装になっている。
// 片方だけ直すと Public Facts と LINE 下書きの数値が食い違う。
// 番犬: frontend/src/lib/blog/insightFromRange.crossCheck.test.ts が両者の出力一致を検証する
// （どちらかを変えるとこのテストが落ちる）。

const MS_PER_DAY = 24 * 60 * 60 * 1000;

function fmtYmdTokyo(d) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Tokyo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(d);
}

function fmtHmTokyo(d) {
  return new Intl.DateTimeFormat("ja-JP", {
    timeZone: "Asia/Tokyo",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(d);
}

function ymdPlusDays(ymd, days) {
  const base = new Date(`${ymd}T00:00:00+09:00`);
  const d = new Date(base.getTime() + days * MS_PER_DAY);
  return fmtYmdTokyo(d);
}

function nightWindowIso(ymd) {
  const from = `${ymd}T19:00:00+09:00`;
  const toYmd = ymdPlusDays(ymd, 1);
  const to = `${toYmd}T05:00:00+09:00`;
  return { from, to, label: "Tonight" };
}

function normalizeIso(s) {
  if (typeof s !== "string") return "";
  return s.replace(/\.(\d{3})\d+/, ".$1");
}

function parseTimestamp(row) {
  const v =
    row?.ts ??
    row?.t ??
    row?.time ??
    row?.datetime ??
    row?.at ??
    row?.created_at ??
    row?.createdAt ??
    null;

  if (v == null) return null;
  if (typeof v === "number" && Number.isFinite(v)) return new Date(v);
  if (typeof v !== "string") return null;

  const s = normalizeIso(v.trim());
  if (!s) return null;

  if (/[zZ]$/.test(s) || /[+-]\d\d:\d\d$/.test(s)) return new Date(s);
  return new Date(s + "+09:00");
}

function pickNumber(obj, keys) {
  for (const k of keys) {
    const n = Number(obj?.[k]);
    if (Number.isFinite(n)) return n;
  }
  return null;
}

function computeTotal(row, totalKeys, menKeys, womenKeys) {
  const total = pickNumber(row, totalKeys);
  if (total != null) return total;
  const men = pickNumber(row, menKeys);
  const women = pickNumber(row, womenKeys);
  if (men != null && women != null) return men + women;
  return null;
}

function collectPoints(rows, fromIso, toIso, options) {
  const from = new Date(fromIso);
  const to = new Date(toIso);
  const shiftMs = (options.shiftDays ?? 0) * MS_PER_DAY;
  const points = [];

  for (const r of rows) {
    const dt = parseTimestamp(r);
    if (!dt) continue;
    const shifted = shiftMs ? new Date(dt.getTime() + shiftMs) : dt;
    if (shifted < from || shifted > to) continue;

    const total = computeTotal(r, options.totalKeys, options.menKeys, options.womenKeys);
    if (!Number.isFinite(total)) continue;

    points.push({ dt: shifted, total });
  }

  points.sort((a, b) => a.dt - b.dt);
  return points;
}

function computeInsight(points) {
  if (points.length === 0) {
    return { peak_time: "", avoid_time: "", crowd_label: "" };
  }

  let peak = points[0];
  let avoid = points[0];
  for (const p of points) {
    if (p.total > peak.total) peak = p;
    if (p.total < avoid.total) avoid = p;
  }

  const max = peak.total;
  let crowd_label = "空き";
  if (max >= 120) crowd_label = "混み";
  else if (max >= 80) crowd_label = "ほどよい";

  return {
    peak_time: fmtHmTokyo(peak.dt),
    avoid_time: fmtHmTokyo(avoid.dt),
    crowd_label,
  };
}

function pickArray(data) {
  if (Array.isArray(data)) return data;
  if (Array.isArray(data?.rows)) return data.rows;
  if (Array.isArray(data?.data)) return data.data;
  return [];
}

export {
  MS_PER_DAY,
  fmtYmdTokyo,
  fmtHmTokyo,
  ymdPlusDays,
  nightWindowIso,
  normalizeIso,
  parseTimestamp,
  pickNumber,
  computeTotal,
  collectPoints,
  computeInsight,
  pickArray,
};
