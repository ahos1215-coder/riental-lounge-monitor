// frontend/src/data/pricing/types.ts
//
// 料金シミュレーターの共有型定義。オリエンタルラウンジ全36店舗（日本国内）に対応する
// ため、以前は nagasaki.ts にあった型定義をここへ切り出した（単一ソース化）。
//
// ■ 対象範囲（2026-07-08 時点）
// stores.json 上の brand="oriental" は38件あるが、料金シミュレーターの対象は
// 「日本国内でページが生存している」36件のみ:
//   - gangnam（ソウル江南）: 日本国内店舗ではないため対象外
//   - sapporo_ag（stores/1）: 公式サイトの店舗ページが 302 でトップページへ
//     リダイレクトされ、事実上ページが消失している（2026-07-08 に生HTTPで確認）。
//     価格データが取得できないため対象外とし、getStorePricing は null を返す
//     （UI側は元々 null で非表示になるので追加のガードは不要）。
// 上記2件を除く37店舗のうち、価格ページが正常に確認できた36店舗を registry.ts に収録する。

export type DayType = "weekday" | "weekend";

/**
 * 相席中の課金バンド。start/end は「開店からの分」ではなく、素直な時刻表現として
 * 24時間表記+オーバーナイト延長（24:00〜30:00 = 翌0:00〜6:00）を使う。
 * 例: 24:00〜Close(06:00) は end="30:00" として表現する。
 *
 * weekday/weekend は null を取り得る（例: 渋谷店の「6時〜Close」は週末のみ販売され、
 * 平日はこの時間帯に到達する前に閉店するため null）。null は「その曜日タイプでは
 * このバンドに滞在が到達しない/販売されていない」ことを意味し、¥0 とは異なる。
 * computeCost.ts はこの null を明示的にガードし、null バンドに滞在が入り込む
 * ケースを検出できるようにする（閉店時刻の設定が正しければ通常は起こらない）。
 */
export type PricingBand = {
  /** 表示用ラベル（公式サイトの表記に準拠） */
  label: string;
  /** "HH:MM" 形式。24時以降は 24:00〜59:59 のレンジで翌日・翌々日を表す */
  start: string;
  end: string;
  /** 平日 10分毎単価（円）。null = 平日はこのバンドに到達しない/販売なし */
  weekday: number | null;
  /** 週末 10分毎単価（円）。null = 週末はこのバンドに到達しない/販売なし */
  weekend: number | null;
};

export type PricingCharges = {
  /** 通常チャージ（円）。アプリチェックインで無料になる */
  entry: number;
  /** 男性1名での来店に加算されるシングルチャージ（円）。相席の有無とは独立の固定費 */
  single: number;
};

/**
 * 相席していない時間の10分単価（店舗ページの「単独」行 = トップページの「単独10分」）。
 * 店舗によって平日・週末で金額が異なる（例: 名古屋・関西エリアの一部店舗は
 * 平日¥220 / 週末¥330）ため、長崎店プロトタイプ時代の単一 perUnit ではなく
 * DayType 別の構造にする。
 */
export type SoloRate = {
  weekday: number;
  weekend: number;
  /** モデルの根拠となるコーポレートトップページ（全店共通） */
  sourceUrl: string;
};

export type PricingTable = {
  storeSlug: string;
  storeName: string;
  /** 課金単位（分）。10分毎課金・切り上げ */
  unitMinutes: number;
  /**
   * 開店・閉店時刻の「両曜日タイプをまたいだ最大範囲」。
   * openTime = 両曜日タイプのうち早い方（UIの入店時刻セレクトの下限）。
   * closeTime = 両曜日タイプのうち遅い方（UIの退店時刻セレクトの上限）。
   * 実際に選べる/計算できる範囲は曜日タイプ別に openTimeByDayType /
   * closeTimeByDayType で絞り込む（例: 渋谷店は openTime="18:00" 共通だが
   * closeTime は週末側の "31:00"（翌07:00）。天満店は openTime が週末側の
   * "17:00"、closeTime は両曜日とも "29:00"（翌05:00））。
   */
  openTime: string;
  closeTime: string;
  /**
   * 曜日タイプ別の実際の開店時刻（"HH:MM"）。ほとんどの店舗は平日・週末で
   * 同一だが、天満店（週末のみ17時開店・平日18時開店）などは異なる。
   */
  openTimeByDayType: Record<DayType, string>;
  /**
   * 曜日タイプ別の実際の閉店時刻（"HH:MM"、翌日側は24:00〜表記）。
   * ほとんどの店舗は平日・週末で同一だが、一部店舗（渋谷・小倉など）は異なる。
   * UIの退店時刻セレクトや validateStayWindow はこちらを優先して使うこと。
   */
  closeTimeByDayType: Record<DayType, string>;
  /** 男性・相席中の時間帯別バンド（開店から閉店まで連続で埋まっている） */
  bands: PricingBand[];
  /** 男性・相席していない時間の単価（曜日タイプ別） */
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
  /**
   * この店舗データに関する注記（UI下部にフッターノートとして表示することがある）。
   * 例: 名古屋AG店の 19:00〜20:00 は公式サイトに明示バンドが無いため、
   * 最初に掲載されているバンドの単価を暫定適用している、等。
   */
  assumptionNotes?: string[];
};
