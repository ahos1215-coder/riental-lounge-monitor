"use client";

import { useMemo, useState } from "react";

import type { PricingTable } from "@/data/pricing/nagasaki";
import {
  computeStayCost,
  computeStayPlans,
  normalizeStayMinutes,
  timeToMinutes,
  type CostResult,
} from "@/lib/pricing/computeCost";
import type { DayType } from "@/lib/pricing";

type Props = {
  pricing: PricingTable;
  /** タイムラインのピーク予測（あれば入店プラン試算をそれに連動させる） */
  peakTimeLabel?: string | null;
  hasForecast?: boolean;
};

const YEN = new Intl.NumberFormat("ja-JP");
function yen(n: number): string {
  return `¥${YEN.format(Math.max(0, Math.round(n)))}`;
}

/** 今日の曜日から平日/週末の初期値を決める（金・土は週末扱い。祝前日は手動選択が必要）。 */
function defaultDayType(): DayType {
  const day = new Date().getDay(); // 0=Sun .. 6=Sat
  return day === 5 || day === 6 ? "weekend" : "weekday";
}

/** 18:00〜翌05:30 の30分刻み選択肢（表示は "HH:MM"、24時以降も24時間表記のまま） */
function buildEntryTimeOptions(): { value: string; label: string }[] {
  const options: { value: string; label: string }[] = [];
  for (let m = timeToMinutes("18:00"); m <= timeToMinutes("29:30"); m += 30) {
    const h = Math.floor(m / 60);
    const min = m % 60;
    const label = `${(h % 24).toString().padStart(2, "0")}:${min.toString().padStart(2, "0")}`;
    options.push({ value: `${h.toString().padStart(2, "0")}:${min.toString().padStart(2, "0")}`, label });
  }
  return options;
}

/** entry+30分〜06:00 の30分刻み選択肢 */
function buildExitTimeOptions(entryHHMM: string): { value: string; label: string }[] {
  const entryMinutes = timeToMinutes(entryHHMM);
  const closeMinutes = timeToMinutes("30:00");
  const options: { value: string; label: string }[] = [];
  for (let m = entryMinutes + 30; m <= closeMinutes; m += 30) {
    const h = Math.floor(m / 60);
    const min = m % 60;
    const label = m === closeMinutes ? "06:00（Close）" : `${(h % 24).toString().padStart(2, "0")}:${min.toString().padStart(2, "0")}`;
    options.push({ value: `${h.toString().padStart(2, "0")}:${min.toString().padStart(2, "0")}`, label });
  }
  return options;
}

function BreakdownTable({ result, dayType }: { result: CostResult; dayType: DayType }) {
  return (
    <div className="mt-3 overflow-x-auto rounded-xl border border-white/10 bg-black/30">
      <table className="w-full min-w-[320px] text-left text-[11px]">
        <thead>
          <tr className="border-b border-white/10 text-slate-400">
            <th className="px-2.5 py-1.5 font-medium">時間帯</th>
            <th className="px-2.5 py-1.5 font-medium">分</th>
            <th className="px-2.5 py-1.5 font-medium">単価/10分</th>
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
      {dayType && null}
    </div>
  );
}

function PriceBoundaryNote({ result, dayType }: { result: CostResult; dayType: DayType }) {
  if (result.boundaries.length === 0) return null;
  return (
    <div className="mt-3 space-y-1.5">
      {result.boundaries.map((b) => (
        <p
          key={b.atLabel}
          className="rounded-lg border border-amber-500/25 bg-amber-500/10 px-2.5 py-1.5 text-[11px] leading-relaxed text-amber-100/90"
        >
          {b.atLabel} 以降は 10分 {yen(b.newPrice)}
          {dayType === "weekday" ? "（週末は別料金）" : ""} に上がります。
        </p>
      ))}
    </div>
  );
}

/** ピーク連動の入店プラン試算セクション */
function PeakPlanSection({
  pricing,
  peakTimeLabel,
  hasForecast,
}: {
  pricing: PricingTable;
  peakTimeLabel?: string | null;
  hasForecast?: boolean;
}) {
  const [dayType, setDayType] = useState<DayType>(defaultDayType());
  const [appCheckin, setAppCheckin] = useState(true);

  // ピーク予測の1時間前を入店時刻の目安にする。予測が無ければ22:00をデフォルト例にする。
  const { entryLabel, isFromForecast } = useMemo(() => {
    if (hasForecast && peakTimeLabel && /^\d{1,2}:\d{2}$/.test(peakTimeLabel)) {
      const peakMinutes = normalizeStayMinutes(peakTimeLabel, pricing.openTime);
      const oneHourBefore = peakMinutes - 60;
      const openMinutes = timeToMinutes(pricing.openTime);
      const clamped = Math.max(openMinutes, oneHourBefore);
      // 30分刻みに丸める
      const rounded = Math.round(clamped / 30) * 30;
      const h = Math.floor(rounded / 60);
      const m = rounded % 60;
      return {
        entryLabel: `${(h % 24).toString().padStart(2, "0")}:${m.toString().padStart(2, "0")}`,
        isFromForecast: true,
      };
    }
    return { entryLabel: "22:00", isFromForecast: false };
  }, [hasForecast, peakTimeLabel, pricing.openTime]);

  const entryMinutes = useMemo(
    () => normalizeStayMinutes(entryLabel, pricing.openTime),
    [entryLabel, pricing.openTime],
  );

  const plans = useMemo(
    () =>
      computeStayPlans(pricing, dayType, entryMinutes, {
        appCheckin,
        solo: false,
      }),
    [pricing, dayType, entryMinutes, appCheckin],
  );

  // 表示中のプランをまとめた1つの CostResult から境界（値上がり）を集める。
  // 一番長い「クローズまで」プランの境界が、他の短いプランの境界も内包する。
  const longestPlan = plans[plans.length - 1];

  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-[12px] font-semibold text-slate-100">ピーク連動の入店プラン試算</h3>
        <div className="flex overflow-hidden rounded-full border border-white/10 text-[11px]">
          <button
            type="button"
            onClick={() => setDayType("weekday")}
            className={`min-h-[28px] px-2.5 font-medium transition ${
              dayType === "weekday" ? "bg-cyan-500/20 text-cyan-100" : "text-slate-400"
            }`}
          >
            平日
          </button>
          <button
            type="button"
            onClick={() => setDayType("weekend")}
            className={`min-h-[28px] px-2.5 font-medium transition ${
              dayType === "weekend" ? "bg-pink-500/20 text-pink-100" : "text-slate-400"
            }`}
          >
            週末
          </button>
        </div>
      </div>

      <p className="mt-1.5 text-[11px] leading-relaxed text-slate-400">
        {isFromForecast ? (
          <>
            ピーク予測 <span className="font-semibold text-slate-200">{peakTimeLabel}</span> — 1時間前の{" "}
            <span className="font-semibold text-slate-200">{entryLabel}</span> に入店した場合
          </>
        ) : (
          <>
            例として <span className="font-semibold text-slate-200">{entryLabel}</span> 入店の場合を試算しています（ピーク予測が出たら自動で連動します）。
          </>
        )}
      </p>

      <label className="mt-2 flex min-h-[28px] items-center gap-2 text-[11px] text-slate-400">
        <input
          type="checkbox"
          checked={appCheckin}
          onChange={(e) => setAppCheckin(e.target.checked)}
          className="h-4 w-4 shrink-0 rounded border-white/20 bg-black/40"
        />
        アプリチェックイン済み（チャージ¥550→無料）
      </label>

      <div className="mt-3 overflow-x-auto rounded-xl border border-white/10 bg-black/30">
        <table className="w-full min-w-[320px] text-left text-[11px]">
          <thead>
            <tr className="border-b border-white/10 text-slate-400">
              <th className="px-2.5 py-1.5 font-medium">滞在</th>
              <th className="px-2.5 py-1.5 font-medium">退店時刻</th>
              <th className="px-2.5 py-1.5 text-right font-medium">料金（男性）</th>
            </tr>
          </thead>
          <tbody>
            {plans.map((p) => (
              <tr key={p.label} className="border-b border-white/5 last:border-0">
                <td className="px-2.5 py-1.5 text-slate-200">{p.label}</td>
                <td className="px-2.5 py-1.5 text-slate-400">{p.exitLabel}</td>
                <td className="px-2.5 py-1.5 text-right font-semibold text-slate-100">
                  {yen(p.result.total)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {longestPlan && <PriceBoundaryNote result={longestPlan.result} dayType={dayType} />}
    </div>
  );
}

/** 自由計算（任意の時間でいくら）セクション */
function FreeCalcSection({ pricing }: { pricing: PricingTable }) {
  const entryOptions = useMemo(() => buildEntryTimeOptions(), []);
  const [dayType, setDayType] = useState<DayType>(defaultDayType());
  const [entryHHMM, setEntryHHMM] = useState("22:00");
  const exitOptions = useMemo(() => buildExitTimeOptions(entryHHMM), [entryHHMM]);
  const [exitHHMM, setExitHHMM] = useState(() => exitOptions[3]?.value ?? exitOptions[0]?.value ?? "24:00");
  const [appCheckin, setAppCheckin] = useState(true);
  const [solo, setSolo] = useState(false);

  const validExitOptions = useMemo(() => buildExitTimeOptions(entryHHMM), [entryHHMM]);
  const effectiveExit = validExitOptions.some((o) => o.value === exitHHMM)
    ? exitHHMM
    : validExitOptions[0]?.value ?? exitHHMM;

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
    <div className="mt-6 border-t border-white/10 pt-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-[12px] font-semibold text-slate-100">自由計算（任意の時間でいくら）</h3>
        <div className="flex overflow-hidden rounded-full border border-white/10 text-[11px]">
          <button
            type="button"
            onClick={() => setDayType("weekday")}
            className={`min-h-[28px] px-2.5 font-medium transition ${
              dayType === "weekday" ? "bg-cyan-500/20 text-cyan-100" : "text-slate-400"
            }`}
          >
            平日
          </button>
          <button
            type="button"
            onClick={() => setDayType("weekend")}
            className={`min-h-[28px] px-2.5 font-medium transition ${
              dayType === "weekend" ? "bg-pink-500/20 text-pink-100" : "text-slate-400"
            }`}
          >
            週末
          </button>
        </div>
      </div>
      <p className="mt-1 text-[10px] text-slate-500">
        今日は自動で{defaultDayType() === "weekend" ? "週末" : "平日"}を選択しています。祝前日などは手動で切り替えてください。
      </p>

      <div className="mt-3 grid grid-cols-2 gap-2">
        <label className="flex flex-col gap-1 text-[11px] text-slate-400">
          入店時刻
          <select
            value={entryHHMM}
            onChange={(e) => {
              const nextEntry = e.target.value;
              setEntryHHMM(nextEntry);
              const nextExitOptions = buildExitTimeOptions(nextEntry);
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

      <div className="mt-3 flex flex-col gap-2">
        <label className="flex min-h-[44px] items-center gap-2 rounded-lg border border-white/10 bg-white/[0.02] px-2.5 text-[12px] text-slate-300">
          <input
            type="checkbox"
            checked={appCheckin}
            onChange={(e) => setAppCheckin(e.target.checked)}
            className="h-4 w-4 shrink-0 rounded border-white/20 bg-black/40"
          />
          アプリチェックイン済み（チャージ¥550→無料・デフォルトON）
        </label>
        <label className="flex min-h-[44px] items-center gap-2 rounded-lg border border-white/10 bg-white/[0.02] px-2.5 text-[12px] text-slate-300">
          <input
            type="checkbox"
            checked={solo}
            onChange={(e) => setSolo(e.target.checked)}
            className="h-4 w-4 shrink-0 rounded border-white/20 bg-black/40"
          />
          おひとり利用（シングルチャージ +¥1,100）
        </label>
      </div>

      {result && (
        <>
          <div className="mt-4 flex items-baseline gap-2">
            <span className="text-[11px] text-slate-400">男性 合計（目安）</span>
            <span className="text-3xl font-black tabular-nums text-cyan-200">{yen(result.total)}</span>
          </div>

          <BreakdownTable result={result} dayType={dayType} />
          <PriceBoundaryNote result={result} dayType={dayType} />

          <div className="mt-3 rounded-xl border border-pink-500/20 bg-pink-500/5 px-3 py-2 text-[11px] text-pink-100/90">
            女性: <span className="font-semibold">{yen(pricing.women.price)}</span>
            <span className="ml-1 text-pink-200/60">（{pricing.women.note}）</span>
          </div>
        </>
      )}
    </div>
  );
}

export function CostSimulatorCard({ pricing, peakTimeLabel, hasForecast }: Props) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-gradient-to-b from-slate-950/95 to-black/90 p-4 shadow-[0_12px_40px_rgba(0,0,0,0.45)] ring-1 ring-white/[0.05]">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-500">
            料金の目安
          </p>
          <p className="mt-0.5 text-[11px] text-slate-400">
            {pricing.storeName}の公式料金表をもとに、入店・退店時刻からその場で計算します。
          </p>
        </div>
      </div>

      <div className="mt-4">
        <PeakPlanSection pricing={pricing} peakTimeLabel={peakTimeLabel} hasForecast={hasForecast} />
      </div>

      <FreeCalcSection pricing={pricing} />

      <div className="mt-5 space-y-1 border-t border-white/10 pt-3 text-[10px] leading-relaxed text-slate-500">
        <p>
          公式サイトの料金表（{pricing.verifiedAt}時点）に基づく参考計算です。実際の料金・適用条件は
          <a
            href={pricing.sourceUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="ml-1 text-slate-400 underline underline-offset-2 hover:text-slate-300"
          >
            公式サイト
          </a>
          でご確認ください。
        </p>
        <p>
          料金は10分毎の課金を前提に、滞在時間を10分単位に切り上げて計算しています（各10分の単価は開始時刻の時間帯で決まります）。
        </p>
        <p>{pricing.weekendRule}</p>
      </div>
    </div>
  );
}
