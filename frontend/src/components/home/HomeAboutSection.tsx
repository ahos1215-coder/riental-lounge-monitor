"use client";

import { FadeIn } from "@/components/ui/FadeIn";
import { STORES, type StoreMeta } from "@/app/config/stores";

/**
 * 「めぐりびとは」の対応ブランド文。店舗数はハードコードせず STORES から
 * ブランド別に導出する（店舗の増減があっても自動的に正しい数になる）。
 * 純粋関数として切り出してテスト可能にしている。
 */
export function buildAboutCoverageLine(stores: Pick<StoreMeta, "brand">[]): string {
  const orientalCount = stores.filter((s) => s.brand === "oriental").length;
  const aisekiyaCount = stores.filter((s) => s.brand === "aisekiya").length;
  const total = orientalCount + aisekiyaCount;
  return `オリエンタルラウンジ${orientalCount}店舗・相席屋${aisekiyaCount}店舗の全${total}店舗に対応しています。今後は他ブランドや二次会スポットにも広げていく予定です。`;
}

export function HomeAboutSection() {
  const coverageLine = buildAboutCoverageLine(STORES);
  return (
          <FadeIn delay={0.1} className="space-y-3">
            <h2 className="text-sm font-semibold text-slate-100">めぐりびとは</h2>
            <div className="rounded-2xl border border-slate-800 bg-slate-950/80 p-4 text-sm leading-relaxed text-slate-100/80">
              <p>
                「めぐりび」は、特別な夜にふさわしい一軒を探すための案内灯です。
                混雑の傾向や男女比、独自の予測モデルをもとに、「いま行くならどこが良さそうか」の参考をお届けします。
              </p>
              <p className="mt-2">{coverageLine}</p>
            </div>
          </FadeIn>
  );
}
