import { buildStoreFullName, getStoreMetaBySlugStrict, isPercentCrowdBrand } from "../../config/stores";
import {
  buildStoreTrendSentences,
  formatTrendBasis,
  summarizeStoreTrend,
} from "@/lib/store/storeTrends";
import { getStoreTrendEntry } from "@/lib/store/storeTrendsData";

/**
 * 店舗ごとの「混みやすい曜日・時間帯」（サーバー描画＝クロール可能なテキスト）。
 * 直近4週ぶんの事前集計 JSON（storeTrends.generated.json）から固定テンプレートで文章化する。
 * データが少ない/古い店舗では何も出さない（summarizeStoreTrend が null）。
 */
export default function StoreTrendsSection({ slug }: { slug: string }) {
  const meta = getStoreMetaBySlugStrict(slug);
  if (!meta) return null;
  const summary = summarizeStoreTrend(getStoreTrendEntry(slug), { now: new Date() });
  if (!summary) return null;

  const percentBrand = isPercentCrowdBrand(meta.brand);
  const sentences = buildStoreTrendSentences(summary, { showGenderRatio: !percentBrand });
  if (sentences.length === 0) return null;

  return (
    <section aria-labelledby="store-trends-heading" className="mx-auto mt-8 w-full max-w-6xl px-4">
      <h2 id="store-trends-heading" className="text-sm font-semibold text-slate-100">
        {buildStoreFullName(meta)}の混みやすい曜日・時間帯
      </h2>
      <p className="mt-1 text-[11px] text-white/50">{formatTrendBasis(summary)}</p>
      <ul className="mt-3 space-y-1.5 text-sm leading-relaxed text-slate-300">
        {sentences.map((t) => (
          <li key={t}>{t}</li>
        ))}
      </ul>
      <p className="mt-3 text-[11px] leading-relaxed text-white/40">
        ※ 5分ごとに記録した店内の人数（相席屋は公式の混雑度％）を、曜日×時間帯ごとに平均したものです。日付が変わった後の時間は前日の夜として数えています（例：土曜0時台＝土曜の夜の0時台）。毎週更新。過去の傾向のため、当日の混み具合とは異なることがあります。
        {percentBrand ? "相席屋は男女別の人数を公開していないため、男女比は載せていません。" : null}
      </p>
    </section>
  );
}
