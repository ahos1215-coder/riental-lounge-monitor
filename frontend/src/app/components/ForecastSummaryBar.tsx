"use client";

import type { ReactNode } from "react";

type ForecastSummaryBarProps = {
  loading: boolean;
  peakSummary: string;
  calmSummary: string;
  signalText: string;
};

function IconTrendingUp() {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M3 17l6-6 4 4 7-7" />
      <path d="M14 8h6v6" />
    </svg>
  );
}

function IconCoffee() {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M3 8h13v6a4 4 0 0 1-4 4H7a4 4 0 0 1-4-4V8z" />
      <path d="M16 10h2a2 2 0 0 1 0 4h-2" />
      <path d="M6 3v2M10 3v2M14 3v2" />
    </svg>
  );
}

function IconZap() {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M13 2L4 14h7l-1 8 9-12h-7l1-8z" />
    </svg>
  );
}

function Card({
  title,
  value,
  icon,
  loading,
}: {
  title: string;
  value: string;
  icon: ReactNode;
  loading: boolean;
}) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.03] p-3 sm:p-4">
      <p className="flex items-center gap-1.5 text-[11px] font-medium text-slate-300 sm:text-xs">
        {icon}
        {title}
      </p>
      {loading ? (
        <div className="mt-2 h-5 w-24 animate-pulse rounded bg-slate-700/70 sm:h-6 sm:w-28" />
      ) : (
        <p className="mt-2 break-words text-sm font-bold leading-snug text-white sm:text-base md:text-lg">
          {value}
        </p>
      )}
    </div>
  );
}

export default function ForecastSummaryBar({
  loading,
  peakSummary,
  calmSummary,
  signalText,
}: ForecastSummaryBarProps) {
  return (
    <section className="rounded-2xl border border-slate-800 bg-slate-950/80 p-3 sm:p-4">
      <div className="grid gap-2 sm:gap-3 md:grid-cols-3">
        <Card
          title="今夜の賑わいピーク目安"
          value={peakSummary}
          icon={<IconTrendingUp />}
          loading={loading}
        />
        <Card
          title="落ち着いて過ごしやすい目安"
          value={calmSummary}
          icon={<IconCoffee />}
          loading={loading}
        />
        <Card
          title="ML 2.0 シグナル"
          value={signalText}
          icon={<IconZap />}
          loading={loading}
        />
      </div>
    </section>
  );
}

