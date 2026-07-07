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
 * 課金バンド。start/end は「開店からの分」ではなく、素直な時刻表現として
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
  /** 男性1名利用時に加算されるシングルチャージ（円） */
  single: number;
};

export type PricingTable = {
  storeSlug: string;
  storeName: string;
  /** 課金単位（分）。10分毎課金・切り上げ */
  unitMinutes: number;
  /** 営業時間（開店・閉店）。閉店は翌日側なので "30:00" 表記 */
  openTime: string;
  closeTime: string;
  /** 男性の時間帯別バンド（開店から閉店まで連続で埋まっている） */
  bands: PricingBand[];
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
  /**
   * 公式サイトの料金表には「単独」という行が Open〜20時 行とは別に独立して存在する
   * （¥220、平日/週末同額）。DOM 上は他の時間帯バンドと同じ形式の行だが、時刻の
   * start/end を持たず、意味を断定できる注釈・脚注がサイト側に無かった。
   * シングルチャージ（男性1名利用+¥1,100）とは別の記載であることは確認済み。
   * 曖昧なため、時間帯バンドには組み込まず注記としてのみ保持する。
   */
  soloRowNote: {
    label: string;
    weekdayPrice: number;
    weekendPrice: number;
    caveat: string;
  };
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
  soloRowNote: {
    label: "単独",
    weekdayPrice: 220,
    weekendPrice: 220,
    caveat:
      "公式サイトの料金表に「単独」という行がありますが、時間帯の指定が無く意味を断定できないため、本シミュレーターの計算には含めていません（詳細は公式サイトでご確認ください）。",
  },
};
