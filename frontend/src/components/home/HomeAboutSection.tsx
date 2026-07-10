"use client";

import { FadeIn } from "@/components/ui/FadeIn";

export function HomeAboutSection() {
  return (
          <FadeIn delay={0.1} className="space-y-3">
            <h2 className="text-sm font-semibold text-slate-100">めぐりびとは</h2>
            <div className="rounded-2xl border border-slate-800 bg-slate-950/80 p-4 text-sm leading-relaxed text-slate-100/80">
              <p>
                「めぐりび」は、特別な夜にふさわしい一軒を探すための案内灯です。
                混雑の傾向や男女比、独自の予測モデルをもとに、「いま行くならどこが良さそうか」の参考をお届けします。
              </p>
              <p className="mt-2">
                まずはオリエンタルラウンジから対応し、今後は他ブランドや二次会スポットにも広げていく予定です。
              </p>
            </div>
          </FadeIn>
  );
}
