import type { ReactNode } from "react";

type PreviewHeaderProps = {};

export default function PreviewHeader(_props: PreviewHeaderProps) {
  return (
    <header className="sticky top-0 z-30 border-b border-slate-800 bg-black/95 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center gap-4 px-4 py-3">
        {/* ブランドロゴ */}
        <div className="flex items-center gap-3">
          <div className="relative h-8 w-8">
            <div className="absolute inset-0 rounded-full border border-amber-300/80 bg-amber-500/5 shadow-[0_0_25px_rgba(251,191,36,0.45)]" />
            <div className="absolute right-0 top-1/2 h-2.5 w-2.5 -translate-y-1/2 translate-x-0.5 rounded-full bg-amber-300 shadow-[0_0_18px_rgba(251,191,36,0.9)]" />
          </div>
          <p className="text-sm font-semibold tracking-[0.35em] text-amber-100">
            めぐりび
          </p>
        </div>

        {/* ナビメニュー（PC） */}
        <nav className="ml-4 hidden items-center gap-5 text-sm text-slate-300 md:flex">
          <NavItem>店舗一覧</NavItem>
          <NavItem>ブログ一覧</NavItem>
          <NavItem>マイページ</NavItem>
        </nav>

        {/* 検索バー */}
        <div className="ml-auto flex flex-1 items-center justify-end gap-2">
          <div className="flex max-w-xs flex-1 items-center gap-2 rounded-full border border-slate-700 bg-slate-950 px-3 py-1.5 text-xs text-slate-200">
            <span className="text-slate-500">🔍</span>
            <input
              type="search"
              placeholder="サイト内を検索（店舗・ブログなど）"
              className="w-full bg-transparent text-xs outline-none placeholder:text-slate-500"
            />
          </div>
        </div>
      </div>
    </header>
  );
}

type NavItemProps = {
  children: ReactNode;
};

function NavItem({ children }: NavItemProps) {
  return (
    <button
      type="button"
      className="text-xs font-medium text-slate-300 transition hover:text-amber-300"
    >
      {children}
    </button>
  );
}
