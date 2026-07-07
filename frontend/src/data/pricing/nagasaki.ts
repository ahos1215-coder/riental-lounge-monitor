// frontend/src/data/pricing/nagasaki.ts
//
// オリエンタルラウンジ長崎（slug: nagasaki）の公式料金データ。
// 出典: https://oriental-lounge.com/stores/38 （2026-07-07 に生HTMLを直接取得して検証）
//
// 検証方法メモ: WebFetch（要約AI経由）は同じページに対して複数回異なる集計結果を返した
// （バンドの対応がずれる/VIP行を混同する等）ため、最終的に生HTMLを直接ダウンロードし、
// `.dl-table-inner` の DOM 構造（<dt>ラベル</dt> と対応する <dd><span>¥xxx</span></dd>）を
// 目視で確認して転記した。以後の再検証もこの「生HTML直読み」方式を推奨する。
//
// ■ 料金モデル（コーポレートトップページで確定・2026-07-07 生HTML検証済み）
// https://oriental-lounge.com/ の #price セクションからの引用:
//   「チャージ」「飲み放題 単独10分 220円～」「飲み放題 相席10分 440円～」
//   「アプリインストールでチャージ無料」
// つまり10分単価は「その時間に相席しているかどうか」で切り替わる:
//   - 相席していない時間（待機・単独で着席）: ¥220/10分（平日・週末同額 = 店舗ページの「単独」行）
//   - 相席中の時間: 下記 bands の時間帯別単価（¥440/500 〜 ¥770/800）
// シングルチャージ¥1,100は「男性1名での来店」に対する別建ての固定費で、上記とは独立。
//
// ■ チャージ金額の注記
// 店舗ページ本文・入店ルールは「チャージ料 550 円」だが、同ページおよびトップページの
// フッターバナーは「チャージ料(500円)」と表記されており、公式サイト内で不整合がある。
// 本データは本文の ¥550 を正として採用する。
//
// 発注時に共有された料金表との差分:
//   共有表: 24:00〜Close = 平日¥660 / 週末¥700
//   公式サイト実測: 24:00〜Close = 平日¥770 / 週末¥800
// 生HTML（下記 dt/dd の対応）を正としてこのファイルは公式サイト実測値を採用している。
// また、共有表にない「22:00〜24:00」の並びも公式サイトでは
//   20:00〜22:00 = 平日¥550 / 週末¥600
//   22:00〜24:00 = 平日¥660 / 週末¥700
// と、共有表より1バンドぶん高い金額にずれている。バンドの区切り時刻（18/20/22/24時）自体は
// 共有表と一致するが、各バンドの金額が全体的に1段階ずつ高い。

export type DayType = "weekday" | "weekend";

/**
 * 相席中の課金バンド。start/end は「開店からの分」ではなく、素直な時刻表現として
 * 24時間表記+オーバーナイト延長（24:00〜30:00 = 翌0:00〜6:00）を使う。
 * 例: 24:00〜Close(06:00) は end="30:00" として表現する。
 */
export type PricingBand = {
  /** 表示用ラベル（公式サイトの表記に準拠） */
  label: string;
  /** "HH:MM" 形式。24時以降は 24:00〜29:59 のレンジで翌日を表す（例: 30:00 = 翌06:00） */
  start: string;
  end: string;
  /** 平日 10分毎単価（円） */
  weekday: number;
  /** 週末 10分毎単価（円） */
  weekend: number;
};

export type PricingCharges = {
  /** 通常チャージ（円）。アプリチェックインで無料になる */
  entry: number;
  /** 男性1名での来店に加算されるシングルチャージ（円）。相席の有無とは独立の固定費 */
  single: number;
};

/**
 * 相席していない時間の10分単価（店舗ページの「単独」行 = トップページの「単独10分」）。
 * 平日・週末同額。実際の会計は「相席していた時間 × バンド単価 + それ以外 × この単価」に
 * なるため、シミュレーターは上限（ずっと相席）と下限（相席なし）の両方を計算する。
 */
export type SoloRate = {
  perUnit: number;
  label: string;
  /** モデルの根拠となるコーポレートトップページ */
  sourceUrl: string;
};

export type PricingTable = {
  storeSlug: string;
  storeName: string;
  /** 課金単位（分）。10分毎課金・切り上げ */
  unitMinutes: number;
  /** 営業時間（開店・閉店）。閉店は翌日側なので "30:00" 表記 */
  openTime: string;
  closeTime: string;
  /** 男性・相席中の時間帯別バンド（開店から閉店まで連続で埋まっている） */
  bands: PricingBand[];
  /** 男性・相席していない時間の単価 */
  soloRate: SoloRate;
  charges: PricingCharges;
  /** 女性は現状フラット¥0（一部有料商品あり） */
  women: {
    price: number;
    note: string;
  };
  /** 週末料金の適用条件（表示用テキスト） */
  weekendRule: string;
  sourceUrl: string;
  /** データを検証した日付（YYYY-MM-DD） */
  verifiedAt: string;
};

export const NAGASAKI_PRICING: PricingTable = {
  storeSlug: "nagasaki",
  storeName: "オリエンタルラウンジ長崎",
  unitMinutes: 10,
  openTime: "18:00",
  closeTime: "30:00", // 翌 06:00
  bands: [
    { label: "Open〜20:00", start: "18:00", end: "20:00", weekday: 440, weekend: 500 },
    { label: "20:00〜22:00", start: "20:00", end: "22:00", weekday: 550, weekend: 600 },
    { label: "22:00〜24:00", start: "22:00", end: "24:00", weekday: 660, weekend: 700 },
    { label: "24:00〜Close", start: "24:00", end: "30:00", weekday: 770, weekend: 800 },
  ],
  soloRate: {
    perUnit: 220,
    label: "相席していない時間",
    sourceUrl: "https://oriental-lounge.com/",
  },
  charges: {
    entry: 550,
    single: 1100,
  },
  women: {
    price: 0,
    note: "食べ放題・飲み放題ともに¥0（一部有料の商品もございます）",
  },
  weekendRule: "金・土曜日および祝日前は週末料金が適用されます。年末年始・GW・お盆などの期間も週末料金となります。",
  sourceUrl: "https://oriental-lounge.com/stores/38",
  verifiedAt: "2026-07-07",
};
