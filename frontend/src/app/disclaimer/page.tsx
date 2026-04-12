import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "免責事項・ご利用にあたって",
  description:
    "めぐりび（MEGRIBI）の免責事項、データの取り扱い、および各相席ブランドとの関係についてご説明します。",
};

export default function DisclaimerPage() {
  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-10">
      <Link
        href="/"
        className="inline-flex items-center gap-2 text-sm text-white/70 transition hover:text-white"
      >
        <span aria-hidden>&larr;</span>
        ホームに戻る
      </Link>

      <h1 className="mt-6 text-2xl font-bold text-white">
        免責事項・ご利用にあたって
      </h1>

      <div className="mt-8 space-y-8 text-sm leading-relaxed text-white/80">
        {/* 1. 非公式サービスであることの明示 */}
        <section>
          <h2 className="text-base font-bold text-white">
            1. 非公式サービスについて
          </h2>
          <p className="mt-3">
            当サービス「めぐりび（MEGRIBI）」は、個人が独自に開発・運営している
            <strong className="text-white">非公式のサードパーティサービス</strong>
            です。掲載されている各相席ラウンジ・飲食ブランド（Oriental
            Lounge、相席屋、JIS 等）の運営企業および関係団体とは、
            一切の提携・協力関係にありません。
          </p>
          <p className="mt-2">
            各ブランドの商標・ロゴマーク等の権利は、それぞれの権利者（各運営企業）に帰属します。
          </p>
        </section>

        {/* 2. 情報の正確性に関する免責 */}
        <section>
          <h2 className="text-base font-bold text-white">
            2. 情報の正確性・リアルタイム性について
          </h2>
          <p className="mt-3">
            当サービスが提供する各店舗の混雑状況（男女別人数および割合）のデータは、
            対象店舗の公式ウェブサイト上で公開されている情報を一定間隔で機械的に
            自動取得した<strong className="text-white">参考値</strong>です。
          </p>
          <p className="mt-2">
            実際の店舗の混雑状況、システムの遅延、または入店の可否を完全に保証するものではありません。
            当サービスの情報に基づいて利用者が被ったいかなる不利益についても、
            運営者は一切の責任を負いません。
          </p>
        </section>

        {/* 3. AI 予測に関する免責 */}
        <section>
          <h2 className="text-base font-bold text-white">
            3. AI 予測について
          </h2>
          <p className="mt-3">
            当サービスが提供する混雑予測は、過去のデータに基づく機械学習モデル（XGBoost）
            による統計的な推定値です。実際の混雑状況とは異なる場合があります。
          </p>
          <p className="mt-2">
            予測の精度は店舗・曜日・天候等の条件により変動します。
            予測結果を参考にした来店判断はすべて利用者ご自身の責任で行ってください。
          </p>
        </section>

        {/* 4. データの知的財産権 */}
        <section>
          <h2 className="text-base font-bold text-white">
            4. データの知的財産権について
          </h2>
          <p className="mt-3">
            当サービス内で表示される人数や割合などの数値データは、
            客観的事実を示すものであり、著作権法上の著作物には該当しません。
            ただし、サイト内に表示される各店舗のブランド名については、
            それぞれの権利者に帰属します。
          </p>
        </section>

        {/* 5. 推計値について */}
        <section>
          <h2 className="text-base font-bold text-white">
            5. 推計値について（一部ブランド）
          </h2>
          <p className="mt-3">
            一部のブランドでは、混雑状況がパーセンテージ（%）で公開されています。
            当サービスでは、公開されている店舗情報（テーブル数等）をもとに
            推定人数を算出して表示する場合があります。
            この推計値は実際の来店人数とは異なることがあります。
          </p>
        </section>

        {/* 6. お問い合わせ */}
        <section>
          <h2 className="text-base font-bold text-white">6. お問い合わせ</h2>
          <p className="mt-3">
            当サービスに関するお問い合わせや、掲載情報に関するご指摘は、
            サービス運営者までご連絡ください。
          </p>
        </section>
      </div>

      <p className="mt-10 text-xs text-white/40">最終更新: 2026年4月12日</p>
    </main>
  );
}
