"use client";

import { useRef } from "react";
import type { PreviewRangeMode } from "../app/hooks/useStorePreviewData";

const RANGE_MODE_OPTIONS: { id: PreviewRangeMode; label: string }[] = [
  { id: "today", label: "今日" },
  { id: "yesterday", label: "昨日" },
  { id: "lastWeek", label: "先週" },
  { id: "custom", label: "カスタム" },
];

type RangeModeSelectorProps = {
  activeRangeMode: PreviewRangeMode;
  onChangeRangeMode: (mode: PreviewRangeMode) => void;
  customDate?: string;
  onChangeCustomDate?: (value: string) => void;
  selectedBaseDate?: string;
};

export default function RangeModeSelector({
  activeRangeMode,
  onChangeRangeMode,
  customDate = "",
  onChangeCustomDate,
  selectedBaseDate,
}: RangeModeSelectorProps) {
  const dateInputRef = useRef<HTMLInputElement | null>(null);

  const openDatePicker = () => {
    const el =
      dateInputRef.current as (HTMLInputElement & { showPicker?: () => void }) | null;
    if (!el) return;
    el.focus();
    el.showPicker?.();
  };

  return (
    <div className="flex flex-col gap-2 rounded-2xl border border-slate-800/70 bg-slate-950/40 px-3 py-2">
      <p className="text-[10px] text-slate-500">表示する日の夜（19:00–05:00）</p>
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap items-center gap-1">
          {RANGE_MODE_OPTIONS.map((opt) => {
            const active = activeRangeMode === opt.id;
            return (
              <button
                key={opt.id}
                type="button"
                onClick={() => {
                  onChangeRangeMode(opt.id);
                  if (opt.id === "custom") openDatePicker();
                }}
                className={[
                  "rounded-full border px-3 py-1 text-[11px] font-semibold transition",
                  active
                    ? "border-amber-300/80 bg-amber-400/10 text-amber-100"
                    : "border-slate-700 bg-slate-950 text-slate-200 hover:border-slate-500",
                ].join(" ")}
              >
                {opt.label}
              </button>
            );
          })}
        </div>

        <div className="flex flex-wrap items-center gap-2 md:ml-auto">
          <input
            ref={dateInputRef}
            type="date"
            value={customDate}
            onChange={(e) => {
              const next = e.target.value;
              onChangeCustomDate?.(next);
              onChangeRangeMode("custom");
            }}
            className="rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-[11px] text-slate-200"
          />
          {selectedBaseDate && (
            <span className="text-[11px] text-slate-500">
              表示: {selectedBaseDate}（19:00-05:00）
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
