"use client";

import { useMemo, useState } from "react";

import type { AisekiyaPricingTable, OrientalPricingTable, PricingTable } from "@/data/pricing/types";
import {
  computeAisekiyaStayCost,
  computeAisekiyaStayPlans,
  computeStayCost,
  computeStayPlans,
  minutesToTimeLabel,
  normalizeStayMinutes,
  timeToMinutes,
  type AisekiyaCostResult,
  type CostResult,
} from "@/lib/pricing/computeCost";
import type { DayType } from "@/lib/pricing";
import { detectAisekiyaDayTypeJst, detectDayTypeJst } from "@/lib/pricing/jpHolidays";
import {
  recommendEntryTime,
  type ForecastSlotLike,
} from "@/lib/pricing/recommendEntryTime";

type Props = {
  pricing: PricingTable;
  /** タイムライン系列（実測+予測）。「今夜の入店の目安」の算出に使う */
  series: ForecastSlotLike[];
  /** 今夜の予測が取得できているか（false なら例示ベースの表示にフォールバック） */
  hasForecast?: boolean;
};

const YEN = new Intl.NumberFormat("ja-JP");
function yen(n: number): string {
  return `¥${YEN.format(Math.max(0, Math.round(n)))}`;
}

/** 店舗の openTime〜closeTime(曜日タイプ別) を30分刻みで列挙する（両ブランド共通・PricingTableBase のみ参照） */
function buildEntryTimeOptions(pricing: PricingTable, dayType: DayType): { value: string; label: string }[] {
  const options: { value: string; label: string }[] = [];
  const openMinutes = timeToMinutes(pricing.openTimeByDayType[dayType]);
  const closeMinutes = timeToMinutes(pricing.closeTimeByDayType[dayType]);
  for (let m = openMinutes; m < closeMinutes; m += 30) {
    const h = Math.floor(m / 60);
    const min = m % 60;
    const label = `${(h % 24).toString().padStart(2, "0")}:${min.toString().padStart(2, "0")}`;
    options.push({ value: `${h.toString().padStart(2, "0")}:${min.toString().padStart(2, "0")}`, label });
  }
  return options;
}

/** entry+30分〜曜日タイプ別の実閉店時刻 を30分刻みで列挙する（両ブランド共通） */
function buildExitTimeOptions(
  pricing: PricingTable,
  dayType: DayType,
  entryHHMM: string,
): { value: string; label: string }[] {
  const entryMinutes = timeToMinutes(entryHHMM);
  const closeMinutes = timeToMinutes(pricing.closeTimeByDayType[dayType]);
  const closeLabelHHMM = minutesToTimeLabel(closeMinutes);
  const options: { value: string; label: string }[] = [];
  for (let m = entryMinutes + 30; m <= closeMinutes; m += 30) {
    const h = Math.floor(m / 60);
    const min = m % 60;
    const label =
      m === closeMinutes
        ? `${closeLabelHHMM}（Close）`
        : `${(h % 24).toString().padStart(2, "0")}:${min.toString().padStart(2, "0")}`;
    options.push({ value: `${h.toString().padStart(2, "0")}:${min.toString().padStart(2, "0")}`, label });
  }
  return options;
}

/**
 * 入店時刻の次に単価が上がる境界（バンド）を返す。オリエンタル専用
 * （相席屋は時間帯バンドが無いフラット単価のため、この「値上がり」概念自体が
 * 存在しない。CostSimulatorCard 側で model==="oriental" の時のみ呼び出す）。
 */
function nextPriceJump(pricing: OrientalPricingTable, dayType: DayType, entryMinutes: number) {
  for (const band of pricing.bands) {
    if (band[dayType] === null) continue;
    const start = timeToMinutes(band.start);
    if (start > entryMinutes) {
      return band;
    }
  }
  return null;
}

function DayTypeToggle({
  dayType,
  onChange,
}: {
  dayType: DayType;
  onChange: (d: DayType) => void;
}) {
  return (
    <div className="flex overflow-hidden rounded-full border border-white/10 text-[11px]">
      <button
        type="button"
        onClick={() => onChange("weekday")}
        className={`min-h-[32px] px-3 font-medium transition ${
          dayType === "weekday" ? "bg-cyan-500/20 text-cyan-100" : "text-slate-400"
        }`}
      >
        平日
      </button>
      <button
        type="button"
        onClick={() => onChange("weekend")}
        className={`min-h-[32px] px-3 font-medium transition ${
          dayType === "weekend" ? "bg-pink-500/20 text-pink-100" : "text-slate-400"
        }`}
      >
        週末
      </button>
    </div>
  );
}

function BreakdownTable({ result }: { result: CostResult }) {
  return (
    <div className="mt-3 overflow-x-auto rounded-xl border border-white/10 bg-black/30">
      <table className="w-full min-w-[300px] text-left text-[11px]">
        <thead>
          <tr className="border-b border-white/10 text-slate-400">
            <th className="px-2.5 py-1.5 font-medium">時間帯</th>
            <th className="px-2.5 py-1.5 font-medium">分</th>
            <th className="px-2.5 py-1.5 font-medium">10分単価</th>
            <th className="px-2.5 py-1.5 text-right font-medium">小計</th>
          </tr>
        </thead>
        <tbody>
          {result.unitsBreakdown.map((row) => (
            <tr key={row.band.label} className="border-b border-white/5 last:border-0">
              <td className="px-2.5 py-1.5 text-slate-200">{row.band.label}</td>
              <td className="px-2.5 py-1.5 text-slate-400">{row.minutes}分</td>
              <td className="px-2.5 py-1.5 text-slate-400">{yen(row.unitPrice)}</td>
              <td className="px-2.5 py-1.5 text-right font-medium text-slate-100">
                {yen(row.subtotal)}
              </td>
            </tr>
          ))}
          {result.charges.map((c) => (
            <tr key={c.label} className="border-b border-white/5 last:border-0">
              <td className="px-2.5 py-1.5 text-slate-400" colSpan={3}>
                {c.label}
              </td>
              <td className="px-2.5 py-1.5 text-right font-medium text-slate-100">{yen(c.amount)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** 相席屋版の内訳テーブル。時間帯バンドが無いため「相席（フラット単価）」の1行 + チャージ類のみ。 */
function AisekiyaBreakdownTable({
  result,
  dayType,
  pricing,
}: {
  result: AisekiyaCostResult;
  dayType: DayType;
  pricing: AisekiyaPricingTable;
}) {
  const taxIncludedUnit = pricing.josekiRateTaxIncluded[dayType];
  return (
    <div className="mt-3 overflow-x-auto rounded-xl border border-white/10 bg-black/30">
      <table className="w-full min-w-[300px] text-left text-[11px]">
        <thead>
          <tr className="border-b border-white/10 text-slate-400">
            <th className="px-2.5 py-1.5 font-medium">内訳</th>
            <th className="px-2.5 py-1.5 font-medium">分</th>
            <th className="px-2.5 py-1.5 font-medium">10分単価</th>
            <th className="px-2.5 py-1.5 text-right font-medium">小計</th>
          </tr>
        </thead>
        <tbody>
          <tr className="border-b border-white/5 last:border-0">
            <td className="px-2.5 py-1.5 text-slate-200">相席（税抜）</td>
            <td className="px-2.5 py-1.5 text-slate-400">{result.totalUnits * pricing.unitMinutes}分</td>
            <td className="px-2.5 py-1.5 text-slate-400">
              {yen(result.unitPrice)}
              <span className="ml-1 text-[9px] text-slate-500">（税込{yen(taxIncludedUnit)}）</span>
            </td>
            <td className="px-2.5 py-1.5 text-right font-medium text-slate-100">
              {yen(result.staySubtotal)}
            </td>
          </tr>
          {result.charges.map((c) => (
            <tr key={c.label} className="border-b border-white/5 last:border-0">
              <td className="px-2.5 py-1.5 text-slate-400" colSpan={3}>
                {c.label}
              </td>
              <td className="px-2.5 py-1.5 text-right font-medium text-slate-100">{yen(c.amount)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** 自由計算（アコーディオン内・オリエンタル版）。曜日タイプはカード上部の共通トグルを使う */
function FreeCalcSection({ pricing, dayType }: { pricing: OrientalPricingTable; dayType: DayType }) {
  const entryOptions = useMemo(() => buildEntryTimeOptions(pricing, dayType), [pricing, dayType]);
  const [entryHHMM, setEntryHHMM] = useState(() => {
    // 既定の22:00がその曜日タイプの選択肢に存在しない店舗（例: 開店が22時以降の
    // 特殊なケースは無いが、念のため）は先頭の選択肢にフォールバックする
    const opts = buildEntryTimeOptions(pricing, dayType);
    return opts.some((o) => o.value === "22:00") ? "22:00" : opts[0]?.value ?? "22:00";
  });
  const exitOptions = useMemo(
    () => buildExitTimeOptions(pricing, dayType, entryHHMM),
    [pricing, dayType, entryHHMM],
  );
  const [exitHHMM, setExitHHMM] = useState(() => exitOptions[3]?.value ?? exitOptions[0]?.value ?? "24:00");
  const [appCheckin, setAppCheckin] = useState(true);
  const [solo, setSolo] = useState(false);

  const effectiveExit = exitOptions.some((o) => o.value === exitHHMM)
    ? exitHHMM
    : exitOptions[0]?.value ?? exitHHMM;

  const result = useMemo(() => {
    try {
      const entryMinutes = normalizeStayMinutes(entryHHMM, pricing.openTime);
      const exitMinutes = normalizeStayMinutes(effectiveExit, pricing.openTime);
      return computeStayCost(pricing, dayType, entryMinutes, exitMinutes, { appCheckin, solo });
    } catch {
      return null;
    }
  }, [pricing, dayType, entryHHMM, effectiveExit, appCheckin, solo]);

  return (
    <div className="pt-3">
      <div className="grid grid-cols-2 gap-2">
        <label className="flex flex-col gap-1 text-[11px] text-slate-400">
          入店時刻
          <select
            value={entryHHMM}
            onChange={(e) => {
              const nextEntry = e.target.value;
              setEntryHHMM(nextEntry);
              const nextExitOptions = buildExitTimeOptions(pricing, dayType, nextEntry);
              if (!nextExitOptions.some((o) => o.value === exitHHMM)) {
                setExitHHMM(nextExitOptions[3]?.value ?? nextExitOptions[0]?.value ?? nextEntry);
              }
            }}
            className="min-h-[44px] rounded-lg border border-white/15 bg-black/40 px-2.5 text-[12px] text-slate-100"
          >
            {entryOptions.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1 text-[11px] text-slate-400">
          退店時刻
          <select
            value={effectiveExit}
            onChange={(e) => setExitHHMM(e.target.value)}
            className="min-h-[44px] rounded-lg border border-white/15 bg-black/40 px-2.5 text-[12px] text-slate-100"
          >
            {exitOptions.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="mt-2 flex flex-col gap-2">
        <label className="flex min-h-[44px] items-center gap-2 rounded-lg border border-white/10 bg-white/[0.02] px-2.5 text-[12px] text-slate-300">
          <input
            type="checkbox"
            checked={appCheckin}
            onChange={(e) => setAppCheckin(e.target.checked)}
            className="h-4 w-4 shrink-0 rounded border-white/20 bg-black/40"
          />
          アプリチェックイン済み（チャージ{yen(pricing.charges.entry)}→無料）
        </label>
        <label className="flex min-h-[44px] items-center gap-2 rounded-lg border border-white/10 bg-white/[0.02] px-2.5 text-[12px] text-slate-300">
          <input
            type="checkbox"
            checked={solo}
            onChange={(e) => setSolo(e.target.checked)}
            className="h-4 w-4 shrink-0 rounded border-white/20 bg-black/40"
          />
          おひとり利用（シングルチャージ +{yen(pricing.charges.single)}）
        </label>
      </div>

      {result && (
        <>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-[11px] text-slate-400">男性 合計（目安）</span>
            <span className="text-2xl font-black tabular-nums text-cyan-200">
              {yen(result.maxTotal)}
            </span>
          </div>

          <BreakdownTable result={result} />

          <div className="mt-2 rounded-xl border border-pink-500/20 bg-pink-500/5 px-3 py-2 text-[11px] text-pink-100/90">
            女性: <span className="font-semibold">{yen(pricing.women.price)}</span>
            <span className="ml-1 text-pink-200/60">（{pricing.women.note}）</span>
          </div>
        </>
      )}
    </div>
  );
}

/** 自由計算（アコーディオン内・相席屋版）。時間帯バンドが無いためシングルチャージのトグルも無い。 */
function AisekiyaFreeCalcSection({ pricing, dayType }: { pricing: AisekiyaPricingTable; dayType: DayType }) {
  const entryOptions = useMemo(() => buildEntryTimeOptions(pricing, dayType), [pricing, dayType]);
  const [entryHHMM, setEntryHHMM] = useState(() => {
    const opts = buildEntryTimeOptions(pricing, dayType);
    return opts.some((o) => o.value === "22:00") ? "22:00" : opts[0]?.value ?? "22:00";
  });
  const exitOptions = useMemo(
    () => buildExitTimeOptions(pricing, dayType, entryHHMM),
    [pricing, dayType, entryHHMM],
  );
  const [exitHHMM, setExitHHMM] = useState(() => exitOptions[3]?.value ?? exitOptions[0]?.value ?? "24:00");
  const [appCheckin, setAppCheckin] = useState(true);

  const effectiveExit = exitOptions.some((o) => o.value === exitHHMM)
    ? exitHHMM
    : exitOptions[0]?.value ?? exitHHMM;

  const result = useMemo(() => {
    try {
      const entryMinutes = normalizeStayMinutes(entryHHMM, pricing.openTime);
      const exitMinutes = normalizeStayMinutes(effectiveExit, pricing.openTime);
      return computeAisekiyaStayCost(pricing, dayType, entryMinutes, exitMinutes, { appCheckin });
    } catch {
      return null;
    }
  }, [pricing, dayType, entryHHMM, effectiveExit, appCheckin]);

  return (
    <div className="pt-3">
      <div className="grid grid-cols-2 gap-2">
        <label className="flex flex-col gap-1 text-[11px] text-slate-400">
          入店時刻
          <select
            value={entryHHMM}
            onChange={(e) => {
              const nextEntry = e.target.value;
              setEntryHHMM(nextEntry);
              const nextExitOptions = buildExitTimeOptions(pricing, dayType, nextEntry);
              if (!nextExitOptions.some((o) => o.value === exitHHMM)) {
                setExitHHMM(nextExitOptions[3]?.value ?? nextExitOptions[0]?.value ?? nextEntry);
              }
            }}
            className="min-h-[44px] rounded-lg border border-white/15 bg-black/40 px-2.5 text-[12px] text-slate-100"
          >
            {entryOptions.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1 text-[11px] text-slate-400">
          退店時刻
          <select
            value={effectiveExit}
            onChange={(e) => setExitHHMM(e.target.value)}
            className="min-h-[44px] rounded-lg border border-white/15 bg-black/40 px-2.5 text-[12px] text-slate-100"
          >
            {exitOptions.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="mt-2 flex flex-col gap-2">
        <label className="flex min-h-[44px] items-center gap-2 rounded-lg border border-white/10 bg-white/[0.02] px-2.5 text-[12px] text-slate-300">
          <input
            type="checkbox"
            checked={appCheckin}
            onChange={(e) => setAppCheckin(e.target.checked)}
            className="h-4 w-4 shrink-0 rounded border-white/20 bg-black/40"
          />
          アプリチェックイン済み（チャージ{yen(pricing.charges.entry)}→無料）
        </label>
      </div>

      {result && (
        <>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-[11px] text-slate-400">男性 合計（目安・相席時間ぶん）</span>
            <span className="text-2xl font-black tabular-nums text-cyan-200">{yen(result.total)}</span>
          </div>

          <AisekiyaBreakdownTable result={result} dayType={dayType} pricing={pricing} />

          <div className="mt-2 rounded-xl border border-cyan-500/20 bg-cyan-500/5 px-3 py-2 text-[11px] text-cyan-100/80">
            相席していない時間は<span className="font-semibold">¥0</span>です。上の金額は「滞在時間すべて相席だった場合」の目安（上限）です。
          </div>

          <div className="mt-2 rounded-xl border border-pink-500/20 bg-pink-500/5 px-3 py-2 text-[11px] text-pink-100/90">
            女性: <span className="font-semibold">{yen(pricing.women.price)}</span>
            <span className="ml-1 text-pink-200/60">（{pricing.women.note}）</span>
          </div>
        </>
      )}
    </div>
  );
}

function OrientalCostSimulatorCard({
  pricing,
  series,
  hasForecast,
}: {
  pricing: OrientalPricingTable;
  series: ForecastSlotLike[];
  hasForecast?: boolean;
}) {
  // 今日の平日/週末を自動判定（金・土・祝前日→週末。深夜〜朝6時は前日の夜として扱う）
  const detection = useMemo(() => detectDayTypeJst(new Date()), []);
  const [dayType, setDayType] = useState<DayType>(detection.dayType);
  const [showRationale, setShowRationale] = useState(false);

  const recommendation = useMemo(
    () => (hasForecast ? recommendEntryTime(series, pricing, { dayType }) : null),
    [hasForecast, series, pricing, dayType],
  );

  // コスト帯の起点: 目安が出ていればその時刻、無ければ22:00（店舗の営業時間外なら開店時刻）の例
  const exampleAnchorHHMM = (() => {
    const openMin = timeToMinutes(pricing.openTimeByDayType[dayType]);
    const candidate = normalizeStayMinutes("22:00", pricing.openTime);
    return candidate >= openMin ? "22:00" : pricing.openTimeByDayType[dayType];
  })();
  const anchorMinutes = recommendation
    ? recommendation.entryDisplayMinutes
    : normalizeStayMinutes(exampleAnchorHHMM, pricing.openTime);
  const anchorLabel = minutesToTimeLabel(anchorMinutes);

  const stayChips = useMemo(
    () =>
      computeStayPlans(pricing, dayType, anchorMinutes, { appCheckin: true, solo: false }).filter(
        (p) => p.label !== "クローズまで",
      ),
    [pricing, dayType, anchorMinutes],
  );

  const jumpBand = nextPriceJump(pricing, dayType, anchorMinutes);
  const detectionLabel =
    detection.reason === "祝前日" ? `${detection.dowLabel}・祝前日` : detection.dowLabel;

  return (
    <div className="rounded-2xl border border-slate-800 bg-gradient-to-b from-slate-950/95 to-black/90 p-4 shadow-[0_12px_40px_rgba(0,0,0,0.45)] ring-1 ring-white/[0.05]">
      {/* ヘッダー: タイトル + 曜日タイプ（自動判定チップ + 手動トグル） */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-500">
          料金の目安
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-full border border-white/10 bg-white/[0.04] px-2.5 py-1 text-[10px] text-slate-300">
            今日（{detectionLabel}）→ {detection.dayType === "weekend" ? "週末" : "平日"}料金
          </span>
          <DayTypeToggle dayType={dayType} onChange={setDayType} />
        </div>
      </div>
      <p className="mt-1.5 text-[10px] leading-relaxed text-slate-500">
        週末料金の対象: 金・土・祝前日（年末年始・GW・お盆も週末料金 → 特別期間は手動で週末を選択）
      </p>

      {/* ① 今夜の入店の目安（ひと目ブロック） */}
      <div className="mt-3 rounded-xl border border-cyan-500/20 bg-cyan-950/20 px-3 py-3">
        <p className="text-[10px] font-semibold tracking-wide text-cyan-200/80">今夜の入店の目安</p>
        {recommendation ? (
          <>
            <p className="mt-1 text-3xl font-black tabular-nums leading-none text-cyan-100">
              {recommendation.entryDisplayLabel}
              <span className="ml-1 text-base font-bold text-cyan-200/70">ごろ</span>
            </p>
            <p className="mt-2 text-[11px] leading-relaxed text-slate-300">
              予測: 女性 約{Math.round(recommendation.womenAvg)}人・男性 約
              {Math.round(recommendation.menAvg)}人／女性比 {recommendation.ratioPct}%
              {recommendation.rising && "・増加中"}
            </p>
            {recommendation.quietNight && (
              <p className="mt-1 text-[11px] text-amber-200/80">今夜は全体的に静かな予測です</p>
            )}
            <button
              type="button"
              onClick={() => setShowRationale((v) => !v)}
              className="mt-2 min-h-[32px] rounded-full border border-white/10 bg-white/[0.03] px-3 text-[10px] text-slate-400 transition hover:text-slate-200"
              aria-expanded={showRationale}
            >
              根拠 {showRationale ? "−" : "+"}
            </button>
            {showRationale && (
              <div className="mt-2 space-y-1 rounded-lg border border-white/[0.06] bg-black/30 px-2.5 py-2 text-[10px] leading-relaxed text-slate-400">
                {recommendation.reasons.map((r) => (
                  <p key={r}>・{r}</p>
                ))}
                <p>・開店直後（90分以内）と、終電後（24:00以降）の時間帯は対象外にしています。</p>
                <p>・入店後90分間の「女性の人数」と「女性比」の予測平均で比較しています。</p>
                <p>・予測人数がとても少ない時間帯は除いています。</p>
              </div>
            )}
          </>
        ) : (
          <>
            <p className="mt-1 text-[13px] font-semibold text-slate-200">
              今夜の予測が出たら表示されます
            </p>
            <p className="mt-1 text-[10px] text-slate-500">
              それまでは {anchorLabel} 入店の例で料金を試算しています。
            </p>
          </>
        )}
      </div>

      {/* ② コスト帯（入店目安の時刻に連動） */}
      <div className="mt-3">
        <p className="text-[11px] text-slate-400">
          <span className="font-semibold text-slate-200">{anchorLabel}</span> 入店・男性の目安
          <span className="ml-1 text-[10px] text-slate-500">（アプリチェックインでチャージ無料の場合）</span>
        </p>
        <div className="mt-2 flex flex-wrap gap-2">
          {stayChips.map((p) => (
            <div
              key={p.label}
              className="flex min-w-[96px] flex-1 flex-col items-center rounded-xl border border-white/10 bg-black/30 px-2 py-2"
            >
              <span className="text-[10px] text-slate-400">{p.label}</span>
              <span className="mt-0.5 text-[15px] font-bold tabular-nums text-slate-100">
                {yen(p.result.maxTotal)}
              </span>
              <span className="text-[9px] text-slate-500">〜{p.exitLabel} 退店</span>
            </div>
          ))}
        </div>
        {jumpBand && jumpBand[dayType] !== null && (
          <p className="mt-2 rounded-lg border border-amber-500/25 bg-amber-500/10 px-2.5 py-1.5 text-[11px] leading-relaxed text-amber-100/90">
            {jumpBand.start} 以降は相席 10分 {yen(jumpBand[dayType] as number)}
            {jumpBand.weekday !== null && jumpBand.weekend !== null && (
              <>
                （{dayType === "weekday" ? `週末 ${yen(jumpBand.weekend)}` : `平日 ${yen(jumpBand.weekday)}`}）
              </>
            )}
            に上がります
          </p>
        )}
      </div>

      {/* ③ 自由計算（アコーディオン・初期は閉じる） */}
      <details className="group mt-3 rounded-xl border border-white/10 bg-white/[0.02]">
        <summary className="flex min-h-[44px] cursor-pointer list-none items-center justify-between px-3 text-[12px] font-semibold text-slate-200 [&::-webkit-details-marker]:hidden">
          自由に計算する（任意の入店・退店時刻）
          <span className="text-slate-500 transition group-open:rotate-180" aria-hidden>
            ▾
          </span>
        </summary>
        <div className="border-t border-white/[0.06] px-3 pb-3">
          <FreeCalcSection pricing={pricing} dayType={dayType} />
        </div>
      </details>

      {/* ④ 店舗固有の注記（nagoya_ag の開店直後ギャップ補完など） */}
      {pricing.assumptionNotes && pricing.assumptionNotes.length > 0 && (
        <div className="mt-3 space-y-1 rounded-lg border border-white/[0.06] bg-black/20 px-2.5 py-2 text-[10px] leading-relaxed text-slate-500">
          {pricing.assumptionNotes.map((note) => (
            <p key={note}>※ {note}</p>
          ))}
        </div>
      )}
    </div>
  );
}

function AisekiyaCostSimulatorCard({
  pricing,
  series,
  hasForecast,
}: {
  pricing: AisekiyaPricingTable;
  series: ForecastSlotLike[];
  hasForecast?: boolean;
}) {
  // 相席屋の曜日区分は「金・土・日・祝日・祝前日」が高料金（オリエンタルの
  // detectDayTypeJst とは異なる。日曜・祝日当日を含む点に注意）。
  const detection = useMemo(() => detectAisekiyaDayTypeJst(new Date()), []);
  const [dayType, setDayType] = useState<DayType>(detection.dayType);
  const [showRationale, setShowRationale] = useState(false);

  const recommendation = useMemo(
    () => (hasForecast ? recommendEntryTime(series, pricing, { dayType }) : null),
    [hasForecast, series, pricing, dayType],
  );

  const exampleAnchorHHMM = (() => {
    const openMin = timeToMinutes(pricing.openTimeByDayType[dayType]);
    const candidate = normalizeStayMinutes("22:00", pricing.openTime);
    return candidate >= openMin ? "22:00" : pricing.openTimeByDayType[dayType];
  })();
  const anchorMinutes = recommendation
    ? recommendation.entryDisplayMinutes
    : normalizeStayMinutes(exampleAnchorHHMM, pricing.openTime);
  const anchorLabel = minutesToTimeLabel(anchorMinutes);

  const stayChips = useMemo(
    () =>
      computeAisekiyaStayPlans(pricing, dayType, anchorMinutes, { appCheckin: true }).filter(
        (p) => p.label !== "クローズまで",
      ),
    [pricing, dayType, anchorMinutes],
  );

  const detectionLabel =
    detection.reason === "祝前日" ? `${detection.dowLabel}・祝前日` : detection.dowLabel;

  return (
    <div className="rounded-2xl border border-slate-800 bg-gradient-to-b from-slate-950/95 to-black/90 p-4 shadow-[0_12px_40px_rgba(0,0,0,0.45)] ring-1 ring-white/[0.05]">
      {/* ヘッダー: タイトル + 曜日タイプ（自動判定チップ + 手動トグル） */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-500">
          料金の目安
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-full border border-white/10 bg-white/[0.04] px-2.5 py-1 text-[10px] text-slate-300">
            今日（{detectionLabel}）→ {detection.dayType === "weekend" ? "週末" : "平日"}料金
          </span>
          <DayTypeToggle dayType={dayType} onChange={setDayType} />
        </div>
      </div>
      {/* 相席屋は日曜日も高料金対象（オリエンタルとは異なるルール）なので専用文言を表示する */}
      <p className="mt-1.5 text-[10px] leading-relaxed text-slate-500">{pricing.weekendRule}</p>

      {/* ① 今夜の入店の目安（ひと目ブロック・ブランド非依存ロジックのため無改変） */}
      <div className="mt-3 rounded-xl border border-cyan-500/20 bg-cyan-950/20 px-3 py-3">
        <p className="text-[10px] font-semibold tracking-wide text-cyan-200/80">今夜の入店の目安</p>
        {recommendation ? (
          <>
            <p className="mt-1 text-3xl font-black tabular-nums leading-none text-cyan-100">
              {recommendation.entryDisplayLabel}
              <span className="ml-1 text-base font-bold text-cyan-200/70">ごろ</span>
            </p>
            <p className="mt-2 text-[11px] leading-relaxed text-slate-300">
              予測: 女性 約{Math.round(recommendation.womenAvg)}人・男性 約
              {Math.round(recommendation.menAvg)}人／女性比 {recommendation.ratioPct}%
              {recommendation.rising && "・増加中"}
            </p>
            {recommendation.quietNight && (
              <p className="mt-1 text-[11px] text-amber-200/80">今夜は全体的に静かな予測です</p>
            )}
            <button
              type="button"
              onClick={() => setShowRationale((v) => !v)}
              className="mt-2 min-h-[32px] rounded-full border border-white/10 bg-white/[0.03] px-3 text-[10px] text-slate-400 transition hover:text-slate-200"
              aria-expanded={showRationale}
            >
              根拠 {showRationale ? "−" : "+"}
            </button>
            {showRationale && (
              <div className="mt-2 space-y-1 rounded-lg border border-white/[0.06] bg-black/30 px-2.5 py-2 text-[10px] leading-relaxed text-slate-400">
                {recommendation.reasons.map((r) => (
                  <p key={r}>・{r}</p>
                ))}
                <p>・開店直後（90分以内）と、終電後（24:00以降）の時間帯は対象外にしています。</p>
                <p>・入店後90分間の「女性の人数」と「女性比」の予測平均で比較しています。</p>
                <p>・予測人数がとても少ない時間帯は除いています。</p>
              </div>
            )}
          </>
        ) : (
          <>
            <p className="mt-1 text-[13px] font-semibold text-slate-200">
              今夜の予測が出たら表示されます
            </p>
            <p className="mt-1 text-[10px] text-slate-500">
              それまでは {anchorLabel} 入店の例で料金を試算しています。
            </p>
          </>
        )}
      </div>

      {/* ② コスト帯（入店目安の時刻に連動）。相席屋はフラット単価のため値上がり注意行は出さない */}
      <div className="mt-3">
        <p className="text-[11px] text-slate-400">
          <span className="font-semibold text-slate-200">{anchorLabel}</span> 入店・男性の目安（相席時間ぶん）
          <span className="ml-1 text-[10px] text-slate-500">（アプリチェックインでチャージ無料の場合）</span>
        </p>
        <div className="mt-2 flex flex-wrap gap-2">
          {stayChips.map((p) => (
            <div
              key={p.label}
              className="flex min-w-[96px] flex-1 flex-col items-center rounded-xl border border-white/10 bg-black/30 px-2 py-2"
            >
              <span className="text-[10px] text-slate-400">{p.label}</span>
              <span className="mt-0.5 text-[15px] font-bold tabular-nums text-slate-100">
                {yen(p.result.total)}
              </span>
              <span className="text-[9px] text-slate-500">〜{p.exitLabel} 退店</span>
            </div>
          ))}
        </div>
        <p className="mt-2 rounded-lg border border-cyan-500/20 bg-cyan-500/10 px-2.5 py-1.5 text-[11px] leading-relaxed text-cyan-100/80">
          相席していない時間は¥0です。上の金額は「滞在時間すべて相席だった場合」の目安です。
        </p>
      </div>

      {/* ③ 自由計算（アコーディオン・初期は閉じる） */}
      <details className="group mt-3 rounded-xl border border-white/10 bg-white/[0.02]">
        <summary className="flex min-h-[44px] cursor-pointer list-none items-center justify-between px-3 text-[12px] font-semibold text-slate-200 [&::-webkit-details-marker]:hidden">
          自由に計算する（任意の入店・退店時刻）
          <span className="text-slate-500 transition group-open:rotate-180" aria-hidden>
            ▾
          </span>
        </summary>
        <div className="border-t border-white/[0.06] px-3 pb-3">
          <AisekiyaFreeCalcSection pricing={pricing} dayType={dayType} />
        </div>
      </details>

      {/* ④ 店舗固有の注記（千葉中央店の深夜加算・池袋東口/上野の営業時間簡略化など） */}
      {pricing.assumptionNotes && pricing.assumptionNotes.length > 0 && (
        <div className="mt-3 space-y-1 rounded-lg border border-white/[0.06] bg-black/20 px-2.5 py-2 text-[10px] leading-relaxed text-slate-500">
          {pricing.assumptionNotes.map((note) => (
            <p key={note}>※ {note}</p>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * 料金の目安カード。pricing.model でオリエンタル（時間帯バンド制）と
 * 相席屋（フラット10分単価制・曜日区分も異なる）を振り分ける。
 * PreviewMainSection.tsx から getStorePricing(slug) の戻り値が null でない
 * ときだけ描画される（36店舗＋相席屋6店舗の計42店舗が対象。他ブランド・
 * データ未整備店舗は元々 pricing===null で非表示）。
 */
export function CostSimulatorCard({ pricing, series, hasForecast }: Props) {
  if (pricing.model === "aisekiya") {
    return <AisekiyaCostSimulatorCard pricing={pricing} series={series} hasForecast={hasForecast} />;
  }
  return <OrientalCostSimulatorCard pricing={pricing} series={series} hasForecast={hasForecast} />;
}
