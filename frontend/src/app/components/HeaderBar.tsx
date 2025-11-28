type Props = {
  onSearch?: (value: string) => void;
};

export function HeaderBar({ onSearch }: Props) {
  return (
    <header className="border-b border-slate-800 bg-black/70 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center gap-6 px-4 py-4">
        <div className="text-xl font-bold tracking-wide text-white">MEGRIBI</div>
        <nav className="flex items-center gap-4 text-sm text-slate-200">
          <NavItem>店舗一覧</NavItem>
          <NavItem>ブログ一覧</NavItem>
          <NavItem>マイページ</NavItem>
        </nav>
        <div className="ml-auto flex items-center gap-2">
          <input
            type="text"
            placeholder="店舗やブログを検索"
            onChange={(e) => onSearch?.(e.target.value)}
            className="w-56 rounded border border-slate-800 bg-slate-900 px-3 py-1 text-sm text-slate-100 placeholder:text-slate-500 focus:border-slate-600 focus:outline-none"
          />
          <button
            type="button"
            className="rounded border border-slate-700 px-3 py-1 text-xs text-slate-200 hover:border-slate-500"
          >
            設定
          </button>
        </div>
      </div>
    </header>
  );
}

function NavItem({ children }: { children: React.ReactNode }) {
  return (
    <span className="cursor-pointer text-slate-300 transition hover:text-white">
      {children}
    </span>
  );
}
