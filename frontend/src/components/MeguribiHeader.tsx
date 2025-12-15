"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

type MeguribiHeaderProps = {
  /** 強制的に検索チップの表示/非表示を切り替えたい場合に使用（未指定なら URL から推定） */
  showSearchChip?: boolean;
};

export function MeguribiHeader({ showSearchChip }: MeguribiHeaderProps) {
  const pathname = usePathname();

  // デフォルトでは /store/ 以下は検索チップを隠し、それ以外では表示
  const isStoreDetail = pathname?.startsWith("/store/");
  const effectiveShowChip =
    showSearchChip !== undefined ? showSearchChip : !isStoreDetail;

  return (
    <header className="sticky top-0 z-30 border-b border-slate-800 bg-black/90 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3">
        {/* ロゴ */}
        <Link href="/" className="flex items-center gap-3">
          <div className="relative h-8 w-8">
            <div className="absolute inset-0 rounded-full border border-amber-300/80 bg-amber-500/5 shadow-[0_0_25px_rgba(251,191,36,0.45)]" />
            <div className="absolute right-0 top-1/2 h-2.5 w-2.5 -translate-y-1/2 translate-x-0.5 rounded-full bg-amber-300 shadow-[0_0_18px_rgba(251,191,36,0.9)]" />
          </div>
          <p className="text-sm font-semibold tracking-[0.35em] text-amber-100">
            めぐりび
          </p>
        </Link>

        {/* ナビ＋検索チップ */}
        <div className="flex items-center gap-6">
          <nav className="flex items-center gap-4 text-xs">
            <Link
              href="/stores"
              className="font-medium text-slate-300 transition hover:text-amber-300"
            >
              店舗一覧
            </Link>
            <Link
              href="/blog"
              className="font-medium text-slate-300 transition hover:text-amber-300"
            >
              ブログ
            </Link>
            <Link
              href="/mypage"
              className="font-medium text-slate-300 transition hover:text-amber-300"
            >
              マイページ
            </Link>
          </nav>

          {effectiveShowChip && (
            <div className="hidden items-center rounded-full border border-slate-700 bg-slate-950 px-3 py-1.5 text-[11px] text-slate-300/80 sm:flex">
              <span className="mr-2 text-[13px]">🔍</span>
              <span>エリア・店舗名</span>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
