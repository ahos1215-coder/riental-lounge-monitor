import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "お問い合わせ",
  description: "めぐりび（MEGRIBI）へのお問い合わせページです。",
};

/**
 * お問い合わせフォームの実URL。オーナーがGoogleフォームを用意でき次第、
 * ここへ https://forms.gle/... を入れればリンクが復活する（空文字の間は「準備中」表示）。
 */
const CONTACT_FORM_URL = "";

export default function ContactPage() {
  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-10">
      <Link
        href="/"
        className="inline-flex items-center gap-2 text-sm text-white/70 transition hover:text-white"
      >
        <span aria-hidden>&larr;</span>
        ホームに戻る
      </Link>

      <h1 className="mt-6 text-2xl font-bold text-white">お問い合わせ</h1>

      <div className="mt-8 space-y-6 text-sm leading-relaxed text-white/80">
        <p>
          めぐりび（MEGRIBI）に関するお問い合わせ、ご意見、掲載情報に関するご指摘は、
          以下のフォームからお送りください。
        </p>

        <div className="rounded-2xl border border-indigo-500/20 bg-indigo-950/10 p-6">
          <p className="text-base font-bold text-white">Google フォームからお問い合わせ</p>
          {CONTACT_FORM_URL ? (
            <>
              <p className="mt-2 text-white/60">
                以下のリンクからお問い合わせフォームを開いてください。
                通常 3 営業日以内にご返信いたします。
              </p>
              <a
                href={CONTACT_FORM_URL}
                target="_blank"
                rel="noopener noreferrer"
                className="mt-4 inline-flex items-center gap-2 rounded-lg bg-indigo-500 px-5 py-2.5 font-semibold text-white shadow-lg shadow-indigo-500/25 transition-all hover:bg-indigo-400"
              >
                お問い合わせフォームを開く
                <span aria-hidden>↗</span>
              </a>
            </>
          ) : (
            <>
              <p className="mt-2 text-white/60">
                お問い合わせフォームは現在準備中です。しばらくお待ちください。
              </p>
              <span
                aria-disabled="true"
                className="mt-4 inline-flex cursor-not-allowed items-center gap-2 rounded-lg bg-white/10 px-5 py-2.5 font-semibold text-white/40"
              >
                準備中
              </span>
            </>
          )}
        </div>

        <div className="space-y-3">
          <h2 className="text-base font-bold text-white">お問い合わせの前に</h2>
          <ul className="list-disc space-y-1 pl-5 text-white/60">
            <li>
              本サービスは個人が運営する非公式サービスです。各相席ブランドへのお問い合わせは
              各ブランドの公式サイトへお願いいたします。
            </li>
            <li>
              表示データの誤りや不具合のご報告は大歓迎です。
            </li>
            <li>
              掲載を希望しない店舗ブランドの運営者様は、本フォームよりご連絡ください。
              速やかに対応いたします。
            </li>
          </ul>
        </div>
      </div>

      <p className="mt-10 text-xs text-white/40">運営: めぐりび (MEGRIBI)</p>
    </main>
  );
}
