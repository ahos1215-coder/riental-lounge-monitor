import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "マイページ | めぐりび",
  description: "めぐりびのマイページ（準備中）です。",
};

export default function MyPage() {
  return (
    <main className="relative min-h-[calc(100vh-80px)] bg-black text-white">
      <div className="mx-auto w-full max-w-3xl px-4 pb-16 pt-10">
        <h1 className="text-3xl font-black tracking-tight">マイページ</h1>
        <p className="mt-4 text-white/60">ここは準備中です。</p>
        <div className="mt-6 rounded-2xl border border-white/10 bg-white/5 p-6 text-sm text-white/70">
          将来的に以下を入れる想定です：
          <ul className="mt-3 list-disc space-y-1 pl-5">
            <li>お気に入り店舗（ピン留め）</li>
            <li>閲覧履歴（直近の店舗に戻る）</li>
            <li>通知設定（雨・混雑・おすすめ）</li>
          </ul>
        </div>
      </div>
    </main>
  );
}