"use client";

import { STORES_PER_PAGE } from "./storesListHelpers";

type StoresPaginationProps = {
  currentPage: number;
  pageCount: number;
  totalStores: number;
  replaceQueryParams: (mutate: (p: URLSearchParams) => void) => void;
};

export function StoresPagination({
  currentPage,
  pageCount,
  totalStores,
  replaceQueryParams,
}: StoresPaginationProps) {
  return (
                  <nav
                    className="mt-6 flex flex-wrap items-center justify-center gap-2 text-xs"
                    aria-label="店舗一覧のページ送り"
                  >
                    <button
                      type="button"
                      disabled={currentPage <= 1}
                      onClick={() => {
                        const next = Math.max(1, currentPage - 1);
                        replaceQueryParams((p) => {
                          if (next <= 1) p.delete("page");
                          else p.set("page", String(next));
                        });
                      }}
                      className="rounded-full border border-slate-600 bg-slate-900/80 px-4 py-2 font-medium text-slate-200 transition hover:border-slate-500 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      前のページ
                    </button>
                    <span className="px-3 text-white/60">
                      {currentPage} / {pageCount} ページ（全 {totalStores} 店舗・1ページ {STORES_PER_PAGE} 店舗）
                    </span>
                    <button
                      type="button"
                      disabled={currentPage >= pageCount}
                      onClick={() => {
                        const next = Math.min(pageCount, currentPage + 1);
                        replaceQueryParams((p) => {
                          if (next <= 1) p.delete("page");
                          else p.set("page", String(next));
                        });
                      }}
                      className="rounded-full border border-slate-600 bg-slate-900/80 px-4 py-2 font-medium text-slate-200 transition hover:border-slate-500 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      次のページ
                    </button>
                  </nav>
  );
}
