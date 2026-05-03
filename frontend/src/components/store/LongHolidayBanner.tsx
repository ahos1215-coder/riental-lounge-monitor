"use client";

import { useEffect, useState } from "react";

type HolidayStatus =
  | { ok: true; date: string; block_length: number; block_position: number; is_long_holiday: boolean; label: string }
  | { ok: false; error: string };

/**
 * 連休期間中のみ表示される注意バナー。
 * バックエンド `/api/holiday_status` が `is_long_holiday=true` のときに表示。
 *
 * ML モデルは過去の連休データをほとんど学習していないため、
 * GW・お盆・年末年始など人の動きが普段と大きく違う期間では予測精度が低下する。
 * このバナーで読者の期待値を調整する目的。
 */
export function LongHolidayBanner() {
  const [status, setStatus] = useState<HolidayStatus | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/holiday_status", { cache: "no-store" })
      .then((r) => r.json() as Promise<HolidayStatus>)
      .then((body) => {
        if (!cancelled) setStatus(body);
      })
      .catch(() => {
        // 取得失敗時はバナーを出さない (静かにフェイル)
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!status || !status.ok || !status.is_long_holiday) return null;

  return (
    <div className="rounded-xl border border-amber-400/40 bg-amber-500/10 px-4 py-3 text-[12px] leading-relaxed text-amber-100">
      <div className="flex items-start gap-2">
        <span className="mt-0.5 text-amber-300" aria-hidden>
          ⚠
        </span>
        <div>
          <span className="mr-1 inline-flex items-center rounded-md bg-amber-500/20 px-1.5 py-0.5 text-[10px] font-bold text-amber-200">
            {status.label}
          </span>
          連休中は普段と異なる人の流れが起きるため、予測との乖離が大きくなる傾向があります。
        </div>
      </div>
    </div>
  );
}
