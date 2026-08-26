/**
 * GA4 アナリティクスのヘルパ（開発者向け衛生管理つき）。
 *
 * 設計方針（オーナー要件: 利用者には一切の可視変更なし・計測はすべて開発者側で静かに行う）:
 *  - 本番ホスト（meguribi.jp / www.meguribi.jp）でのみ GA を有効化する。localhost・
 *    Vercel プレビュー・開発環境では gtag を一切ロードせず、イベントも発火しない。
 *  - `?dev=1` を付けて訪問した端末は localStorage に永続フラグを持ち、GA 公式のオプトアウト
 *    （window['ga-disable-<ID>']=true）で恒久的に計測対象外になる。`?dev=0` で解除。
 *    UI フィードバックは console.info の1行のみ（画面表示は一切変えない）。
 *  - すべてのカスタムイベントはこの `track()` を通す。GA 不在/無効時は完全 no-op。
 *
 * 測定 ID（`NEXT_PUBLIC_GA_MEASUREMENT_ID`）は HTML に載る性質の公開情報であり秘密ではない。
 */

import type { PreviewRangeMode } from "@/lib/forecast/types";
import type { SecondVenuePurpose } from "@/app/config/secondVenueMapLinks";

export const GA_MEASUREMENT_ID = process.env.NEXT_PUBLIC_GA_MEASUREMENT_ID ?? "";

/** GA を有効化してよい唯一のホスト名（本番）。 */
export const PRODUCTION_HOSTNAMES = ["meguribi.jp", "www.meguribi.jp"] as const;

/** localStorage に持つ開発者オプトアウトフラグのキー。 */
export const DEV_OPTOUT_KEY = "meguribi:ga-dev-optout";

/** 純粋関数: ホスト名が本番か（window 非依存＝ユニットテスト容易）。 */
export function isProductionHostname(hostname: string): boolean {
  return (PRODUCTION_HOSTNAMES as readonly string[]).includes(hostname);
}

/**
 * 純粋関数: GA を発火してよいかの単一の真偽判定。
 * すべての判断材料を引数で受け取り副作用を持たない（＝網羅的にユニットテストする対象）。
 * 「測定 ID がある」かつ「本番ホスト」かつ「開発者オプトアウトしていない」の全てを満たす時のみ true。
 */
export function shouldEnableAnalytics(input: {
  measurementId: string;
  hostname: string;
  devOptedOut: boolean;
}): boolean {
  return (
    input.measurementId.length > 0 &&
    isProductionHostname(input.hostname) &&
    !input.devOptedOut
  );
}

/**
 * カスタムイベント名の唯一の正本（SSOT）。2026-08-26 計測レビューR2対応: 実発火していた8種 +
 * 前ラウンドで追加した2種（official_site_click / second_venue_click）+ 本ラウンドで追加する
 * 露出2種（official_site_view / second_venue_view。レビュー§4-2: 送客クリックには露出分母が
 * 無く「表示されていない」のか「表示されたが押されない」のか区別できなかったため、この2面だけに
 * 追加する。広範な decision_card_view 群は見送り）。
 * `report_read` は `report_view` に改名した（mount 時に発火する実態に名前を合わせた。
 * 呼び出し側の書き換えは frontend/src/components/ReportViewTracker.tsx で別班が対応）。
 * ここに無い名前は track() の型エラーになる＝「イベント名は union で閉じる」を強制する。
 * Python 週報 `scripts/analytics_weekly_report.py` の `KNOWN_CUSTOM_EVENTS` と手動同期すること
 * （あちらは12種 + legacy alias `report_read`。テスト側でこの配列の中身を固定し、ズレに気づけるようにする）。
 */
export const ANALYTICS_EVENT_NAMES = [
  "store_view",
  "report_view",
  "favorite_add",
  "favorite_remove",
  "compare_add_store",
  "range_mode_change",
  "cost_sim_interact",
  "related_store_click",
  "official_site_click",
  "second_venue_click",
  "official_site_view",
  "second_venue_view",
] as const;

export type AnalyticsEventName = (typeof ANALYTICS_EVENT_NAMES)[number];

/**
 * イベント別の必須パラメータ型（2026-08-26 計測レビューR2対応）。
 *
 * 旧型は `[key: string]: string | number | boolean | undefined` という index signature を
 * 持っており、必須パラメータの欠落・旧キー（`slug` 等）・typo が全て型チェックを素通りしていた
 * （レビュー2-2「index signatureは移行後も誤キーを許す」）。実呼び出し側の store_slug 統一移行は
 * 完了しているため、緩い型を残す理由がなくなった。イベント名ごとに必須パラメータを固定する。
 * 値は「現在の実発火」に合わせて定義する（例: cost_sim_interact / official_site_click の
 * brand は現状 oriental|aisekiya の2値しか送っていないため、その2値で閉じる）。
 */
export type AnalyticsEventParamsByName = {
  store_view: { store_slug: string; store_label: string };
  report_view: { store_slug: string; report_type: "daily" | "weekly" };
  favorite_add: { store_slug: string };
  favorite_remove: { store_slug: string };
  compare_add_store: { store_slug: string };
  range_mode_change: { store_slug: string; mode: PreviewRangeMode };
  cost_sim_interact: { store_slug: string; brand: "oriental" | "aisekiya" };
  related_store_click: { store_slug: string; from_slug: string };
  official_site_click: {
    store_slug: string;
    brand: "oriental" | "aisekiya";
    destination_domain: string;
  };
  second_venue_click: {
    store_slug: string;
    venue_kind: SecondVenuePurpose;
    destination_domain: string;
  };
  official_site_view: { store_slug: string; brand: "oriental" | "aisekiya" };
  second_venue_view: { store_slug: string };
};

type GtagWindow = Window & {
  gtag?: (...args: unknown[]) => void;
  dataLayer?: unknown[];
};

function getBrowserWindow(): GtagWindow | null {
  return typeof window === "undefined" ? null : (window as GtagWindow);
}

/** 現在の端末が開発者オプトアウト中か（ブラウザ外/private mode では false）。 */
export function isDevOptedOut(): boolean {
  const w = getBrowserWindow();
  if (!w) return false;
  try {
    return w.localStorage.getItem(DEV_OPTOUT_KEY) === "1";
  } catch {
    return false;
  }
}

/**
 * GA 公式のオプトアウトフラグ window['ga-disable-<ID>'] を設定する。
 * gtag が初期化される前（＝どの beacon よりも前）に呼ぶことでレース無く恒久除外できる。
 * disabled=false で再有効化（?dev=0 のとき）。測定 ID 未設定時は no-op。
 */
export function setGaDisableFlag(disabled: boolean): void {
  const w = getBrowserWindow();
  if (!w || !GA_MEASUREMENT_ID) return;
  (w as unknown as Record<string, unknown>)[`ga-disable-${GA_MEASUREMENT_ID}`] = disabled;
}

function toSearchParams(
  search: string | URLSearchParams | null | undefined,
): URLSearchParams {
  if (search == null) return new URLSearchParams();
  if (typeof search === "string") return new URLSearchParams(search);
  return search;
}

/**
 * URL の ?dev=1 / ?dev=0 を解釈し、端末単位の永続オプトアウトフラグ（localStorage）を更新する。
 * 反映後のオプトアウト状態に合わせて ga-disable フラグを（gtag ロード前に）立てる/降ろす。
 * 戻り値は「現在オプトアウト中か」。ブラウザ外では常に false。
 */
export function syncDevOptOutFromQuery(
  search: string | URLSearchParams | null | undefined,
): boolean {
  const w = getBrowserWindow();
  if (!w) return false;
  const dev = toSearchParams(search).get("dev");
  try {
    if (dev === "1") {
      w.localStorage.setItem(DEV_OPTOUT_KEY, "1");
      console.info(
        "[analytics] 開発者オプトアウトを有効化しました（この端末では GA を計測しません）。",
      );
    } else if (dev === "0") {
      w.localStorage.removeItem(DEV_OPTOUT_KEY);
      console.info(
        "[analytics] 開発者オプトアウトを解除しました（本番では GA 計測が有効に戻ります）。",
      );
    }
  } catch {
    // private mode / quota 超過は無視
  }
  const optedOut = isDevOptedOut();
  // ビーコンより前に必ずオプトアウト状態を反映する（レースセーフ）。
  setGaDisableFlag(optedOut);
  return optedOut;
}

/** GA が現在アクティブか（イベント/ページビューを送ってよいか）。 */
export function analyticsEnabled(): boolean {
  const w = getBrowserWindow();
  return shouldEnableAnalytics({
    measurementId: GA_MEASUREMENT_ID,
    hostname: w ? w.location.hostname : "",
    devOptedOut: isDevOptedOut(),
  });
}

function gtag(...args: unknown[]): void {
  getBrowserWindow()?.gtag?.(...args);
}

/**
 * すべてのカスタムイベントの唯一の入口。GA 不在/無効時（非本番ホスト・開発者オプトアウト・
 * 測定 ID 未設定・SSR）は完全 no-op。コンポーネント側は gtag を直接触らずこの関数だけを呼ぶ。
 *
 * 2026-08-26 計測レビューR2対応: イベント名 `name` に応じて `params` の型を
 * `AnalyticsEventParamsByName` から引く generic にした。必須パラメータの欠落・旧キー・typo は
 * ここでコンパイルエラーになる（呼び出し側を直接見る必要はない）。
 */
export function track<K extends AnalyticsEventName>(
  name: K,
  params: AnalyticsEventParamsByName[K],
): void {
  if (!analyticsEnabled()) return;
  gtag("event", name, params);
}

/** 後方互換エイリアス（既存の store_view / report_view / favorite_* もこの guarded 経路を通る）。 */
export const sendEvent = track;

/**
 * 仮想ページビュー（SPA 遷移）を送る。無効時は no-op。
 *
 * 2026-08-26 計測レビューR2対応: 従来は `gtag("config", ID, { page_path: url })` を使っていたが、
 * GA4 公式の gtag config が受け付けるパラメータは `page_title` / `page_location` /
 * `send_page_view` のみで `page_path` は非公式（ドキュメントに存在しない）。公式の手動送信方式
 * である `gtag("event", "page_view", { page_location, page_title })` に変更する。
 * 初回PVは従来どおり GoogleAnalytics.tsx の `<Script id="ga4-init">` 内の
 * `gtag('config', ID)` が送る設計を変えない（初回=config、以後=event page_view、の
 * 2経路構成は維持。検証済みの単一送信設計＝初回はgtag未定義でno-opになりconfigのみが送る）。
 */
export function sendPageView(url: string): void {
  if (!analyticsEnabled()) return;
  const w = getBrowserWindow();
  const origin = w ? w.location.origin : "";
  gtag("event", "page_view", {
    page_location: origin + url,
    page_title: typeof document !== "undefined" ? document.title : undefined,
  });
}
