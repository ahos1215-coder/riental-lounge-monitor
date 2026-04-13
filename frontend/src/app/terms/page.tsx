import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "利用規約",
  description: "めぐりび（MEGRIBI）のサービス利用規約です。",
};

export default function TermsPage() {
  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-10">
      <Link
        href="/"
        className="inline-flex items-center gap-2 text-sm text-white/70 transition hover:text-white"
      >
        <span aria-hidden>&larr;</span>
        ホームに戻る
      </Link>

      <h1 className="mt-6 text-2xl font-bold text-white">利用規約</h1>

      <div className="mt-8 space-y-8 text-sm leading-relaxed text-white/80">
        <section>
          <h2 className="text-base font-bold text-white">第1条（適用）</h2>
          <p className="mt-3">
            本規約は、めぐりび（以下「本サービス」）の利用に関する条件を定めるものです。
            利用者は本サービスを利用することにより、本規約に同意したものとみなします。
          </p>
        </section>

        <section>
          <h2 className="text-base font-bold text-white">第2条（サービスの内容）</h2>
          <p className="mt-3">
            本サービスは、相席ラウンジ等の混雑状況を公開情報に基づいて収集・分析し、
            来店タイミングの判断材料となる参考情報を提供する非公式のサードパーティサービスです。
          </p>
          <p className="mt-2">
            本サービスは各相席ブランドの運営企業とは一切の提携・協力関係にありません。
          </p>
        </section>

        <section>
          <h2 className="text-base font-bold text-white">第3条（免責事項）</h2>
          <p className="mt-3">
            本サービスが提供する情報（混雑状況、予測、レポート等）は参考値であり、
            正確性・完全性・リアルタイム性を保証するものではありません。
          </p>
          <p className="mt-2">
            本サービスの情報に基づいて利用者が行った判断・行動により生じた
            いかなる損害についても、運営者は一切の責任を負いません。
          </p>
        </section>

        <section>
          <h2 className="text-base font-bold text-white">第4条（禁止事項）</h2>
          <ul className="mt-3 list-disc space-y-1 pl-5">
            <li>本サービスのデータを商用目的で無断転載・再配布する行為</li>
            <li>本サービスのシステムに対する不正アクセスや過度な負荷をかける行為</li>
            <li>他の利用者または第三者の権利を侵害する行為</li>
            <li>法令または公序良俗に違反する行為</li>
          </ul>
        </section>

        <section>
          <h2 className="text-base font-bold text-white">第5条（サービスの変更・停止）</h2>
          <p className="mt-3">
            運営者は、事前の通知なく本サービスの内容を変更、または提供を停止することがあります。
            これにより利用者に生じた損害について、運営者は一切の責任を負いません。
          </p>
        </section>

        <section>
          <h2 className="text-base font-bold text-white">第6条（知的財産権）</h2>
          <p className="mt-3">
            本サービス内で表示される人数や割合などの数値データは客観的事実を示すものです。
            サイト内に表示される各店舗のブランド名・ロゴ等の商標権は、それぞれの権利者に帰属します。
            本サービスのデザイン・コード・分析ロジック等の知的財産権は運営者に帰属します。
          </p>
        </section>

        <section>
          <h2 className="text-base font-bold text-white">第7条（規約の変更）</h2>
          <p className="mt-3">
            運営者は、必要に応じて本規約を変更することがあります。
            変更後の規約は本ページに掲載した時点で効力を生じます。
          </p>
        </section>
      </div>

      <p className="mt-10 text-xs text-white/40">制定日: 2026年4月13日</p>
    </main>
  );
}
