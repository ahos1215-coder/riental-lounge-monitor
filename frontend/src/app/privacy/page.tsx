import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "プライバシーポリシー",
  description: "めぐりび（MEGRIBI）のプライバシーポリシーです。",
};

export default function PrivacyPage() {
  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-10">
      <Link
        href="/"
        className="inline-flex items-center gap-2 text-sm text-white/70 transition hover:text-white"
      >
        <span aria-hidden>&larr;</span>
        ホームに戻る
      </Link>

      <h1 className="mt-6 text-2xl font-bold text-white">プライバシーポリシー</h1>

      <div className="mt-8 space-y-8 text-sm leading-relaxed text-white/80">
        <section>
          <h2 className="text-base font-bold text-white">1. 収集する情報</h2>
          <p className="mt-3">本サービスでは、以下の情報を収集する場合があります。</p>
          <ul className="mt-2 list-disc space-y-1 pl-5">
            <li>
              <strong className="text-white">アクセスログ</strong>:
              IP アドレス、ブラウザ種別、アクセス日時、閲覧ページ等の情報を、
              サービスの運用・改善目的で自動的に記録します。
            </li>
            <li>
              <strong className="text-white">Cookie / ローカルストレージ</strong>:
              お気に入り店舗や閲覧履歴の保存、および Google Analytics による
              アクセス解析のために使用します。
            </li>
          </ul>
        </section>

        <section>
          <h2 className="text-base font-bold text-white">2. Google Analytics の利用</h2>
          <p className="mt-3">
            本サービスでは、利用状況の把握とサービス改善を目的として
            Google Analytics（Google LLC 提供）を使用しています。
          </p>
          <p className="mt-2">
            Google Analytics は Cookie を使用してアクセス情報を収集しますが、
            個人を特定する情報は含まれません。収集されたデータは Google の
            プライバシーポリシーに基づいて管理されます。
          </p>
          <p className="mt-2">
            Google Analytics のデータ収集を無効にしたい場合は、
            ブラウザの Cookie 設定を変更するか、Google が提供するオプトアウトアドオンをご利用ください。
          </p>
        </section>

        <section>
          <h2 className="text-base font-bold text-white">3. 個人情報の取り扱い</h2>
          <p className="mt-3">
            本サービスでは、会員登録やログイン機能を提供しておらず、
            氏名・メールアドレス・電話番号等の個人情報を意図的に収集することはありません。
          </p>
          <p className="mt-2">
            お問い合わせフォームからご連絡いただいた場合、回答に必要な範囲でのみ
            情報を利用し、第三者への提供は行いません。
          </p>
        </section>

        <section>
          <h2 className="text-base font-bold text-white">4. 表示データについて</h2>
          <p className="mt-3">
            本サービスが表示する相席ラウンジ等の混雑状況（男女別人数・割合）は、
            対象店舗の公式サイト上で一般公開されている情報を自動的に収集したものです。
            個人を特定できる情報は一切含まれていません。
          </p>
        </section>

        <section>
          <h2 className="text-base font-bold text-white">5. 第三者への提供</h2>
          <p className="mt-3">
            収集した情報を、法令に基づく場合を除き、第三者に提供することはありません。
          </p>
        </section>

        <section>
          <h2 className="text-base font-bold text-white">6. ポリシーの変更</h2>
          <p className="mt-3">
            本ポリシーは、必要に応じて変更することがあります。
            変更後のポリシーは本ページに掲載した時点で効力を生じます。
          </p>
        </section>
      </div>

      <p className="mt-10 text-xs text-white/40">制定日: 2026年4月13日</p>
    </main>
  );
}
