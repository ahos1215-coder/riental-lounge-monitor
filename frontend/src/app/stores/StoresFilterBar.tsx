"use client";

import type { Dispatch, SetStateAction } from "react";
import { STORE_REGION_BUTTON_LABEL } from "../config/stores";
import { BRAND_TABS, type BrandFilter } from "./storesListHelpers";

type StoresFilterBarProps = {
  query: string;
  setQuery: Dispatch<SetStateAction<string>>;
  brandFilter: BrandFilter;
  setBrandFilter: Dispatch<SetStateAction<BrandFilter>>;
  replaceQueryParams: (mutate: (p: URLSearchParams) => void) => void;
  regionFilter: string | null;
  regionTabIds: string[];
};

export function StoresFilterBar({
  query,
  setQuery,
  brandFilter,
  setBrandFilter,
  replaceQueryParams,
  regionFilter,
  regionTabIds,
}: StoresFilterBarProps) {
  return (
          <section>
            <div className="rounded-xl border border-white/10 bg-black/50 p-4">
              <div className="flex flex-wrap items-center gap-3">
                <div className="flex min-w-[220px] flex-1 items-center rounded-full border border-slate-700 bg-slate-950 px-3 py-1.5 text-xs text-slate-200">
                  <span className="mr-2 text-[13px] text-slate-400">🔍</span>
                  <input
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="店舗名・エリアで検索（例：渋谷、福岡）"
                    className="flex-1 bg-transparent text-xs outline-none placeholder:text-slate-500"
                  />
                </div>

                <div className="flex flex-wrap items-center gap-1">
                  {BRAND_TABS.map((tab) => (
                    <button
                      key={tab.id}
                      type="button"
                      onClick={() => {
                        setBrandFilter(tab.id);
                        replaceQueryParams((p) => {
                          p.delete("page");
                        });
                      }}
                      className={[
                        "rounded-full px-3 py-1 text-[11px] font-medium transition",
                        brandFilter === tab.id
                          ? "bg-slate-100 text-slate-900"
                          : "bg-slate-900/60 text-slate-300 hover:bg-slate-800",
                      ].join(" ")}
                    >
                      {tab.label}
                    </button>
                  ))}
                </div>
                <div className="mt-3 w-full border-t border-white/10 pt-3">
                  <p className="mb-2 text-[11px] font-medium text-white/45">
                    地域で絞り込み
                  </p>
                  <div
                    className="flex flex-wrap gap-1.5"
                    role="group"
                    aria-label="地域で絞り込み"
                  >
                    <button
                      type="button"
                      onClick={() => {
                        replaceQueryParams((p) => {
                          p.delete("region");
                          p.delete("page");
                        });
                      }}
                      className={[
                        "rounded-full px-3 py-1 text-[11px] font-medium transition",
                        regionFilter === null
                          ? "bg-indigo-500/90 text-white"
                          : "bg-slate-900/60 text-slate-300 hover:bg-slate-800",
                      ].join(" ")}
                    >
                      すべて
                    </button>
                    {regionTabIds.map((rid) => (
                      <button
                        key={rid}
                        type="button"
                        onClick={() => {
                          replaceQueryParams((p) => {
                            p.set("region", rid);
                            p.delete("page");
                          });
                        }}
                        className={[
                          "rounded-full px-3 py-1 text-[11px] font-medium transition",
                          regionFilter === rid
                            ? "bg-indigo-500/90 text-white"
                            : "bg-slate-900/60 text-slate-300 hover:bg-slate-800",
                        ].join(" ")}
                      >
                        {STORE_REGION_BUTTON_LABEL[rid] ?? rid}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </section>
  );
}
