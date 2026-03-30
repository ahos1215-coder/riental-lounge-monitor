"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Store, BarChart3, GitCompareArrows, BookOpen, User, Search, Menu, X } from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/cn";

type MeguribiHeaderProps = {
  showSearchChip?: boolean;
};

const NAV_ITEMS = [
  { href: "/stores", label: "店舗一覧", icon: Store },
  { href: "/reports", label: "AI予測", icon: BarChart3 },
  { href: "/compare", label: "比較", icon: GitCompareArrows },
  { href: "/blog", label: "ブログ", icon: BookOpen },
  { href: "/mypage", label: "マイページ", icon: User },
] as const;

export function MeguribiHeader({ showSearchChip }: MeguribiHeaderProps) {
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);

  const isStoreDetail = pathname?.startsWith("/store/");
  const effectiveShowChip =
    showSearchChip !== undefined ? showSearchChip : !isStoreDetail;

  return (
    <header className="sticky top-0 z-30 border-b border-slate-800/80 bg-black/85 backdrop-blur-xl">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3">
        {/* ロゴ */}
        <Link href="/" className="group flex items-center gap-3">
          <div className="relative h-8 w-8 transition-transform duration-300 group-hover:scale-110">
            <div className="absolute inset-0 rounded-full border border-amber-300/80 bg-amber-500/5 shadow-[0_0_25px_rgba(251,191,36,0.45)]" />
            <div className="absolute right-0 top-1/2 h-2.5 w-2.5 -translate-y-1/2 translate-x-0.5 rounded-full bg-amber-300 shadow-[0_0_18px_rgba(251,191,36,0.9)]" />
          </div>
          <p className="text-sm font-semibold tracking-[0.35em] text-amber-100 transition-colors group-hover:text-amber-200">
            めぐりび
          </p>
        </Link>

        {/* Desktop nav */}
        <div className="hidden items-center gap-5 md:flex">
          <nav className="flex items-center gap-1">
            {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
              const active = pathname === href || pathname?.startsWith(href + "/");
              return (
                <Link
                  key={href}
                  href={href}
                  className={cn(
                    "flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium transition-all duration-200",
                    active
                      ? "bg-amber-500/10 text-amber-200"
                      : "text-slate-400 hover:bg-white/5 hover:text-slate-100",
                  )}
                >
                  <Icon size={14} strokeWidth={active ? 2.5 : 2} />
                  {label}
                </Link>
              );
            })}
          </nav>

          {effectiveShowChip && (
            <Link
              href="/stores"
              className="flex items-center gap-2 rounded-full border border-slate-700/80 bg-slate-900/80 px-3 py-1.5 text-[11px] text-slate-400 transition-all hover:border-slate-600 hover:text-slate-200"
            >
              <Search size={12} />
              <span>エリア・店舗名</span>
            </Link>
          )}
        </div>

        {/* Mobile menu button */}
        <button
          type="button"
          onClick={() => setMobileOpen(!mobileOpen)}
          className="rounded-lg p-2 text-slate-400 transition hover:bg-white/5 hover:text-white md:hidden"
          aria-label={mobileOpen ? "メニューを閉じる" : "メニューを開く"}
        >
          {mobileOpen ? <X size={20} /> : <Menu size={20} />}
        </button>
      </div>

      {/* Mobile nav */}
      {mobileOpen && (
        <nav className="border-t border-slate-800/60 bg-black/95 px-4 pb-4 pt-2 md:hidden">
          {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
            const active = pathname === href || pathname?.startsWith(href + "/");
            return (
              <Link
                key={href}
                href={href}
                onClick={() => setMobileOpen(false)}
                className={cn(
                  "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-all",
                  active
                    ? "bg-amber-500/10 text-amber-200"
                    : "text-slate-400 hover:bg-white/5 hover:text-slate-100",
                )}
              >
                <Icon size={16} strokeWidth={active ? 2.5 : 2} />
                {label}
              </Link>
            );
          })}
        </nav>
      )}
    </header>
  );
}
