"use client";

import { FC } from "react";
import type { ForecastPoint } from "../types/forecast";

type Props = {
  visible: boolean;
  onToggle: () => void;
  nextHour: ForecastPoint[];
  today: ForecastPoint[];
};

export const DebugPanel: FC<Props> = ({
  visible,
  onToggle,
  nextHour,
  today,
}) => {
  return (
    <div className="mt-6">
      <button
        type="button"
        onClick={onToggle}
        className="rounded-md border border-slate-600 px-3 py-1 text-xs font-medium text-slate-100 hover:bg-slate-800"
      >
        {visible ? "デバッグ情報を隠す" : "デバッグ情報を表示"}
      </button>

      {visible && (
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          <div className="rounded-lg border border-slate-700 bg-slate-900/70 p-3 text-xs text-slate-200">
            <div className="mb-1 font-semibold text-slate-100">next_hour raw JSON</div>
            <pre className="max-h-80 overflow-auto whitespace-pre-wrap">
              {JSON.stringify(nextHour, null, 2)}
            </pre>
          </div>
          <div className="rounded-lg border border-slate-700 bg-slate-900/70 p-3 text-xs text-slate-200">
            <div className="mb-1 font-semibold text-slate-100">forecast_today raw JSON</div>
            <pre className="max-h-80 overflow-auto whitespace-pre-wrap">
              {JSON.stringify(today, null, 2)}
            </pre>
          </div>
        </div>
      )}
    </div>
  );
};
