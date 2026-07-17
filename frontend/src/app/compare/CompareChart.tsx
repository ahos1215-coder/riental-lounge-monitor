"use client";

import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { isPercentCrowdBrand, type BrandId } from "@/app/config/stores";

export type CompareChartStoreData = {
  label: string;
  brand: BrandId;
};

type CompareChartProps = {
  chartData: Record<string, unknown>[];
  selectedSlugs: string[];
  storeDataMap: Record<string, CompareChartStoreData | undefined>;
  colors: string[];
  formatTime: (ts: number) => string;
};

/** 人数(オリエンタル)系列は左軸、占有率%(相席屋)系列は右軸に割り当てる Recharts の yAxisId。 */
export const COUNT_AXIS_ID = "count";
export const PERCENT_AXIS_ID = "pct";

export type CompareAxisConfig = {
  /** 人数(人)軸を描くか */
  showCountAxis: boolean;
  /** 占有率(%)軸を描くか */
  showPercentAxis: boolean;
  /** 人数と%の両方があり、2軸(左=人数 / 右=%)にするか */
  dual: boolean;
};

/**
 * 選択店舗のブランド構成から、必要な y 軸を決める。
 * - 人数系列(オリエンタル/JIS)と占有率%系列(相席屋)は単位が違うため同一縦軸に重ねない。
 * - 両方あれば 2 軸（左=人数 / 右=%）。片方だけなら単一軸（余計な空軸を出さない）。
 */
export function resolveCompareAxes(brands: BrandId[]): CompareAxisConfig {
  let hasPercent = false;
  let hasCount = false;
  for (const b of brands) {
    if (isPercentCrowdBrand(b)) hasPercent = true;
    else hasCount = true;
  }
  // 何も無い（データ未到着）ときは従来同様、人数の単一軸を出す。
  if (!hasCount && !hasPercent) hasCount = true;
  return {
    showCountAxis: hasCount,
    showPercentAxis: hasPercent,
    dual: hasCount && hasPercent,
  };
}

/** その店舗系列を割り当てる y 軸の id（%なら右軸候補 / それ以外は人数軸）。 */
export function axisIdForBrand(brand: BrandId): string {
  return isPercentCrowdBrand(brand) ? PERCENT_AXIS_ID : COUNT_AXIS_ID;
}

/**
 * ツールチップの数値表示（rank15 バグ修正）。
 * Recharts に渡す値は補間・演算を経て浮動小数点の生値（例: 26.111711784503775）に
 * なり得るため、四捨五入した整数 + 単位で表示する（人/％は小数で意味を持たない）。
 * 数値化できない値はそのまま素通しする（防御的フォールバック）。
 */
export function formatCompareTooltipValue(value: unknown, unit: string): string {
  const n = Number(value);
  const display = Number.isFinite(n) ? Math.round(n) : value;
  return `${display}${unit}`;
}

/**
 * 混雑推移の比較チャート（Recharts）。
 * Recharts (+d3) は First Load JS への影響が大きい（gzip 換算で ~113KB）ため、
 * /compare のページ本体からは切り離し、店舗選択後に next/dynamic(ssr:false) で
 * 遅延ロードする（店舗詳細ページの PreviewMainSection と同じパターン）。
 *
 * 人数(オリエンタル)系列と占有率%(相席屋)系列は単位が異なるため、同一縦軸に重ねると
 * 「人数の方が数値が大きいので常に上に見える」誤読を生む。両方が混在する比較では
 * 左軸=人数 / 右軸=% の 2 軸に分離し、それぞれの単位で高さを比べられるようにする。
 */
export default function CompareChart({
  chartData,
  selectedSlugs,
  storeDataMap,
  colors,
  formatTime,
}: CompareChartProps) {
  const brands = selectedSlugs.map(
    (slug) => storeDataMap[slug]?.brand ?? "oriental",
  );
  const axes = resolveCompareAxes(brands);

  return (
    <section className="mt-8 rounded-2xl border border-white/10 bg-black/40 p-4 md:p-6">
      <h2 className="text-lg font-bold">混雑推移の比較</h2>
      <p className="mt-1 text-xs text-white/50">
        実線 = 実測、点線 = ML 予測（相席屋は席の埋まり具合 % / オリエンタルは人数）
        {axes.dual ? "。単位が違うため 左軸=人数 / 右軸=% に分けています" : ""}
      </p>
      <div className="mt-4 h-72 w-full min-w-0">
        <ResponsiveContainer width="100%" height={288}>
          <LineChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" opacity={0.5} />
            <XAxis
              type="number"
              dataKey="ts"
              domain={["dataMin", "dataMax"]}
              tickFormatter={(v) => formatTime(v)}
              stroke="#94a3b8"
              tick={{ fill: "#94a3b8", fontSize: 10 }}
            />
            {axes.showCountAxis && (
              <YAxis
                yAxisId={COUNT_AXIS_ID}
                orientation="left"
                stroke="#94a3b8"
                tick={{ fill: "#94a3b8", fontSize: 10 }}
                label={{
                  value: "人",
                  angle: 0,
                  position: "insideTopLeft",
                  fill: "#64748b",
                  fontSize: 10,
                }}
              />
            )}
            {axes.showPercentAxis && (
              <YAxis
                yAxisId={PERCENT_AXIS_ID}
                orientation={axes.dual ? "right" : "left"}
                domain={[0, 100]}
                stroke="#94a3b8"
                tick={{ fill: "#94a3b8", fontSize: 10 }}
                label={{
                  value: "%",
                  angle: 0,
                  position: axes.dual ? "insideTopRight" : "insideTopLeft",
                  fill: "#64748b",
                  fontSize: 10,
                }}
              />
            )}
            <Tooltip
              contentStyle={{ backgroundColor: "#0f172a", border: "1px solid #334155", borderRadius: 8 }}
              labelFormatter={(_, payload) => {
                const row = payload?.[0]?.payload as { label?: string } | undefined;
                return row?.label ?? "";
              }}
              formatter={(value, _name, item) => {
                const key = String(item?.dataKey ?? "");
                const slug = key.replace(/^(actual_|forecast_)/, "");
                const unit = isPercentCrowdBrand(storeDataMap[slug]?.brand ?? "oriental") ? "%" : "人";
                return [formatCompareTooltipValue(value, unit), item?.name ?? ""];
              }}
            />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            {selectedSlugs.map((slug, i) => {
              const data = storeDataMap[slug];
              const name = data?.label ?? slug;
              const brand = data?.brand ?? "oriental";
              const unit = isPercentCrowdBrand(brand) ? "%" : "人";
              const yAxisId = axisIdForBrand(brand);
              return [
                <Line
                  key={`actual_${slug}`}
                  yAxisId={yAxisId}
                  type="monotone"
                  dataKey={`actual_${slug}`}
                  name={`${name}（実測・${unit}）`}
                  stroke={colors[i]}
                  strokeWidth={2}
                  dot={false}
                  isAnimationActive={false}
                  connectNulls={false}
                />,
                <Line
                  key={`forecast_${slug}`}
                  yAxisId={yAxisId}
                  type="monotone"
                  dataKey={`forecast_${slug}`}
                  name={`${name}（予測・${unit}）`}
                  stroke={colors[i]}
                  strokeWidth={1.5}
                  strokeDasharray="6 3"
                  dot={false}
                  isAnimationActive={false}
                  connectNulls={false}
                />,
              ];
            })}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}
