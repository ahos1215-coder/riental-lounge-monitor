// frontend/src/data/pricing/raw.ts
//
// オリエンタルラウンジ全店舗（日本国内・36店舗）の公式料金の生データ。
// 各店舗の公式ページ（https://oriental-lounge.com/stores/<id>）から生HTMLを直接
// 取得し、`.dl-table-inner` の DOM 構造（<dt>ラベル</dt> と対応する
// <dd><span>¥xxx</span></dd>）を機械的に抽出して転記した（要約AI経由のWebFetchは
// 同じページに対して複数回異なる集計結果を返すことが確認されているため不採用。
// 詳細な検証方針は build.ts 冒頭のコメントを参照）。
//
// 検証日: 2026-07-08。本ロールアウト作業で全36店舗の生HTMLを再取得し、
// 価格表（.dl-table-inner）と「営業時間」セクション（stance-time-wrap、
// 平日/週末それぞれの開店〜閉店）の両方をクロスチェックした:
//   - 価格表（バンド構成・単独単価・チャージ額）: 完全一致 = 差分ゼロ
//     （長崎店は既存の手動データ frontend/src/data/pricing/nagasaki.ts とも
//     完全一致）
//   - 営業時間: 12店舗（ebisu, kashiwa, kokura, machida, nagoya_nishiki,
//     osaka_ekimae, shibuya, shibuya_ag, tenma, ueno, ueno_ag, utsunomiya）で
//     平日と週末の開店・閉店時刻が異なることが判明し、openHWeekend /
//     closeHWeekend で修正済み（各店舗のコメント参照）。tenma は初回スクレイプの
//     closeH=6 が誤りで、正しくは5であることも判明し修正した。
//
// ■ フィールドの意味
//   openH / closeH: 平日の開店・閉店時刻（24h表記。closeHは翌日側）。
//   openHWeekend / closeHWeekend: 週末がこれと異なる場合のみ指定
//             （省略時は平日と同一とみなす）。
//   soloRate: 相席していない時間（「単独」行）の10分単価。曜日タイプ別
//   bands:    相席中の時間帯別バンド。startH/endH は24h+表記
//             （例: 24-30 = 当日24:00〜翌06:00）。weekday/weekend が null の
//             バンドは「その曜日タイプでは販売されていない/到達しない」ことを示す
//             （渋谷店の「6時〜Close」は週末専用で平日は null）。
//             多くの店舗は「24時〜Close」のような単一バンドを両曜日タイプで
//             共有しており、週末が平日より遅く閉店する場合でも専用バンド行は
//             無い（= 価格表上は両曜日同額）。この場合 computeCost.ts が
//             最終バンドの単価を各曜日タイプの実際の閉店時刻まで延長して適用する
//             （「Close」は各曜日の実際の閉店を指す動的な意味と解釈）。
//   charges:  single=男性1名利用時のシングルチャージ、entry=通常チャージ
//             （アプリチェックインで無料）。全店共通の金額なのでブランド共通の
//             定数として扱うが、将来店舗ごとに異なる可能性に備えて店舗単位で保持する
//
// ■ 既知の欠落・除外店舗（getStorePricing は該当 slug に対し null を返す）
//   sapporo_ag（stores/1）: 2026-07-08 時点で公式ページが 302 でトップページへ
//     リダイレクトされ、事実上ページが消失している。日本国内の oriental ブランド
//     37店舗のうち、価格データを確認できたのはこの36店舗のみ。
//   gangnam（stores/34、ソウル江南）: 日本国内店舗ではないため対象外
// これら2店舗は本ファイルに一切登場しない（意図的な欠落）。

export type RawPricingBand = {
  label: string;
  startH: number;
  endH: number;
  weekday: number | null;
  weekend: number | null;
};

export type RawStorePricing = {
  slug: string;
  sourceUrl: string;
  /** 平日の開店時刻（24h表記）。週末も同じ場合は openHWeekend を省略してよい。 */
  openH: number;
  /** 平日の閉店時刻（24h表記、翌日側）。週末も同じ場合は closeHWeekend を省略してよい。 */
  closeH: number;
  /**
   * 週末の開店時刻が平日と異なる場合のみ指定する（例: 天満店は週末17時開店・
   * 平日18時開店）。省略時は openH と同じとみなす。
   */
  openHWeekend?: number;
  /**
   * 週末の閉店時刻が平日と異なる場合のみ指定する（例: 渋谷店・小倉店など、
   * 週末は平日より遅くまで営業する店舗が多い）。省略時は closeH と同じとみなす。
   * 2026-07-08 に全36店舗の「営業時間」セクションを生HTMLで再確認し、値を設定した。
   */
  closeHWeekend?: number;
  soloRate: { weekday: number; weekend: number };
  bands: RawPricingBand[];
  charges: { single: number; entry: number };
};

export const PRICING_VERIFIED_AT = "2026-07-08";

export const RAW_ORIENTAL_PRICING: Record<string, RawStorePricing> = {
  ebisu: {
    slug: "ebisu",
    sourceUrl: "https://oriental-lounge.com/stores/35",
    // 2026-07-08 生HTML再確認: 平日18時〜05時、週末18時〜06時（週末は1時間遅い）。
    // 価格表は両曜日で同じ「24時〜Close」バンドを共有しているため、週末の
    // 延長1時間ぶんの専用レートは価格表上に存在しない（渋谷店のような
    // weekday:null の専用バンド行は無い）。
    openH: 18,
    closeH: 5,
    closeHWeekend: 6,
    soloRate: { weekday: 330, weekend: 330 },
    bands: [
      { label: "Open〜20時", startH: 18, endH: 20, weekday: 550, weekend: 880 },
      { label: "20時〜22時", startH: 20, endH: 22, weekday: 660, weekend: 1100 },
      { label: "22時〜24時", startH: 22, endH: 24, weekday: 880, weekend: 1200 },
      { label: "24時〜Close", startH: 24, endH: 29, weekday: 990, weekend: 1500 },
    ],
    charges: { single: 1100, entry: 550 },
  },
  fukuoka: {
    slug: "fukuoka",
    sourceUrl: "https://oriental-lounge.com/stores/15",
    openH: 19,
    closeH: 6,
    soloRate: { weekday: 220, weekend: 220 },
    bands: [
      { label: "Open〜20時", startH: 19, endH: 20, weekday: 700, weekend: 800 },
      { label: "20時〜22時", startH: 20, endH: 22, weekday: 700, weekend: 800 },
      { label: "22時〜24時", startH: 22, endH: 24, weekday: 770, weekend: 880 },
      { label: "24時〜Close", startH: 24, endH: 30, weekday: 770, weekend: 880 },
    ],
    charges: { single: 1100, entry: 550 },
  },
  hamamatsu: {
    slug: "hamamatsu",
    sourceUrl: "https://oriental-lounge.com/stores/31",
    openH: 18,
    closeH: 6,
    soloRate: { weekday: 220, weekend: 220 },
    bands: [
      { label: "Open〜20時", startH: 18, endH: 20, weekday: 440, weekend: 440 },
      { label: "20時〜22時", startH: 20, endH: 22, weekday: 550, weekend: 660 },
      { label: "22時〜24時", startH: 22, endH: 24, weekday: 660, weekend: 880 },
      { label: "24時〜Close", startH: 24, endH: 30, weekday: 660, weekend: 880 },
    ],
    charges: { single: 1100, entry: 550 },
  },
  hiroshima_ag: {
    slug: "hiroshima_ag",
    sourceUrl: "https://oriental-lounge.com/stores/14",
    openH: 18,
    closeH: 6,
    soloRate: { weekday: 220, weekend: 220 },
    bands: [
      { label: "Open〜20時", startH: 18, endH: 20, weekday: 500, weekend: 600 },
      { label: "20時〜22時", startH: 20, endH: 22, weekday: 600, weekend: 700 },
      { label: "22時〜24時", startH: 22, endH: 24, weekday: 660, weekend: 770 },
      { label: "24時〜Close", startH: 24, endH: 30, weekday: 770, weekend: 880 },
    ],
    charges: { single: 1100, entry: 550 },
  },
  kagoshima: {
    slug: "kagoshima",
    sourceUrl: "https://oriental-lounge.com/stores/19",
    openH: 18,
    closeH: 6,
    soloRate: { weekday: 220, weekend: 220 },
    bands: [
      { label: "Open〜20時", startH: 18, endH: 20, weekday: 500, weekend: 600 },
      { label: "20時〜22時", startH: 20, endH: 22, weekday: 700, weekend: 800 },
      { label: "22時〜24時", startH: 22, endH: 24, weekday: 700, weekend: 800 },
      { label: "24時〜Close", startH: 24, endH: 30, weekday: 770, weekend: 880 },
    ],
    charges: { single: 1100, entry: 550 },
  },
  kanazawa_ag: {
    slug: "kanazawa_ag",
    sourceUrl: "https://oriental-lounge.com/stores/36",
    openH: 19,
    closeH: 7,
    soloRate: { weekday: 330, weekend: 330 },
    bands: [
      { label: "Open〜20時", startH: 19, endH: 20, weekday: 440, weekend: 700 },
      { label: "20時〜22時", startH: 20, endH: 22, weekday: 550, weekend: 770 },
      { label: "22時〜24時", startH: 22, endH: 24, weekday: 660, weekend: 770 },
      { label: "24時〜Close", startH: 24, endH: 31, weekday: 770, weekend: 880 },
    ],
    charges: { single: 1100, entry: 550 },
  },
  kashiwa: {
    slug: "kashiwa",
    sourceUrl: "https://oriental-lounge.com/stores/42",
    // 2026-07-08 生HTML再確認: 平日18時〜02時、週末18時〜05時（週末は3時間遅い）。
    // 価格表は両曜日で同じ「24時〜Close」バンドを共有（専用バンド行は無い）。
    openH: 18,
    closeH: 2,
    closeHWeekend: 5,
    soloRate: { weekday: 220, weekend: 220 },
    bands: [
      { label: "Open〜20時", startH: 18, endH: 20, weekday: 550, weekend: 660 },
      { label: "20時〜22時", startH: 20, endH: 22, weekday: 660, weekend: 770 },
      { label: "22時〜24時", startH: 22, endH: 24, weekday: 660, weekend: 880 },
      { label: "24時〜Close", startH: 24, endH: 26, weekday: 770, weekend: 880 },
    ],
    charges: { single: 1100, entry: 550 },
  },
  kobe: {
    slug: "kobe",
    sourceUrl: "https://oriental-lounge.com/stores/13",
    openH: 18,
    closeH: 6,
    soloRate: { weekday: 220, weekend: 330 },
    bands: [
      { label: "Open〜20時", startH: 18, endH: 20, weekday: 600, weekend: 700 },
      { label: "20時〜22時", startH: 20, endH: 22, weekday: 600, weekend: 700 },
      { label: "22時〜24時", startH: 22, endH: 24, weekday: 800, weekend: 900 },
      { label: "24時〜Close", startH: 24, endH: 30, weekday: 800, weekend: 900 },
    ],
    charges: { single: 1100, entry: 550 },
  },
  kokura: {
    slug: "kokura",
    sourceUrl: "https://oriental-lounge.com/stores/16",
    // 2026-07-08 生HTML再確認: 平日18時〜02時、週末18時〜05時（週末は3時間遅い）。
    // 価格表は両曜日で同じ「24時〜Close」バンドを共有（専用バンド行は無い）。
    openH: 18,
    closeH: 2,
    closeHWeekend: 5,
    soloRate: { weekday: 220, weekend: 220 },
    bands: [
      { label: "Open〜20時", startH: 18, endH: 20, weekday: 500, weekend: 550 },
      { label: "20時〜22時", startH: 20, endH: 22, weekday: 550, weekend: 660 },
      { label: "22時〜24時", startH: 22, endH: 24, weekday: 660, weekend: 770 },
      { label: "24時〜Close", startH: 24, endH: 26, weekday: 660, weekend: 880 },
    ],
    charges: { single: 1100, entry: 550 },
  },
  kumamoto: {
    slug: "kumamoto",
    sourceUrl: "https://oriental-lounge.com/stores/22",
    openH: 18,
    closeH: 6,
    soloRate: { weekday: 220, weekend: 220 },
    bands: [
      { label: "Open〜20時", startH: 18, endH: 20, weekday: 500, weekend: 600 },
      { label: "20時〜22時", startH: 20, endH: 22, weekday: 600, weekend: 700 },
      { label: "22時〜24時", startH: 22, endH: 24, weekday: 660, weekend: 770 },
      { label: "24時〜Close", startH: 24, endH: 30, weekday: 770, weekend: 880 },
    ],
    charges: { single: 1100, entry: 550 },
  },
  kyoto: {
    slug: "kyoto",
    sourceUrl: "https://oriental-lounge.com/stores/9",
    openH: 18,
    closeH: 5,
    soloRate: { weekday: 220, weekend: 330 },
    bands: [
      { label: "Open〜20時", startH: 18, endH: 20, weekday: 500, weekend: 600 },
      { label: "20時〜22時", startH: 20, endH: 22, weekday: 600, weekend: 700 },
      { label: "22時〜24時", startH: 22, endH: 24, weekday: 800, weekend: 800 },
      { label: "24時〜Close", startH: 24, endH: 29, weekday: 800, weekend: 900 },
    ],
    charges: { single: 1100, entry: 550 },
  },
  machida: {
    slug: "machida",
    sourceUrl: "https://oriental-lounge.com/stores/6",
    // 2026-07-08 生HTML再確認: 平日19時〜04時、週末18時〜05時
    // （週末は1時間早く開店・1時間遅く閉店）。
    openH: 19,
    closeH: 4,
    openHWeekend: 18,
    closeHWeekend: 5,
    soloRate: { weekday: 220, weekend: 220 },
    bands: [
      { label: "Open〜20時", startH: 19, endH: 20, weekday: 550, weekend: 660 },
      { label: "20時〜22時", startH: 20, endH: 22, weekday: 660, weekend: 770 },
      { label: "22時〜24時", startH: 22, endH: 24, weekday: 660, weekend: 880 },
      { label: "24時〜Close", startH: 24, endH: 28, weekday: 770, weekend: 990 },
    ],
    charges: { single: 1100, entry: 550 },
  },
  miyazaki: {
    slug: "miyazaki",
    sourceUrl: "https://oriental-lounge.com/stores/18",
    openH: 18,
    closeH: 6,
    soloRate: { weekday: 220, weekend: 220 },
    bands: [
      { label: "Open〜20時", startH: 18, endH: 20, weekday: 550, weekend: 660 },
      { label: "20時〜22時", startH: 20, endH: 22, weekday: 550, weekend: 660 },
      { label: "22時〜24時", startH: 22, endH: 24, weekday: 660, weekend: 770 },
      { label: "24時〜Close", startH: 24, endH: 30, weekday: 660, weekend: 770 },
    ],
    charges: { single: 1100, entry: 550 },
  },
  nagasaki: {
    slug: "nagasaki",
    sourceUrl: "https://oriental-lounge.com/stores/38",
    openH: 18,
    closeH: 6,
    soloRate: { weekday: 220, weekend: 220 },
    bands: [
      { label: "Open〜20時", startH: 18, endH: 20, weekday: 440, weekend: 500 },
      { label: "20時〜22時", startH: 20, endH: 22, weekday: 550, weekend: 600 },
      { label: "22時〜24時", startH: 22, endH: 24, weekday: 660, weekend: 700 },
      { label: "24時〜Close", startH: 24, endH: 30, weekday: 770, weekend: 800 },
    ],
    charges: { single: 1100, entry: 550 },
  },
  nagoya_ag: {
    slug: "nagoya_ag",
    sourceUrl: "https://oriental-lounge.com/stores/32",
    openH: 19,
    closeH: 7,
    soloRate: { weekday: 220, weekend: 330 },
    // 注意: 公式サイトの価格表は「20時〜22時」から始まり、開店(19:00)〜20:00の
    // 明示バンドが存在しない（2026-07-08 生HTML再確認済み）。build.ts の
    // fillOpeningGapWithEarliestBand が「20時〜22時」の単価を19:00〜20:00にも
    // 暫定適用する（¥0にはしない）。この暫定措置は PricingTable.assumptionNotes に
    // 記録し、UI フッターにも注記する。
    bands: [
      { label: "20時〜22時", startH: 20, endH: 22, weekday: 660, weekend: 770 },
      { label: "22時〜24時", startH: 22, endH: 24, weekday: 700, weekend: 880 },
      { label: "24時〜Close", startH: 24, endH: 31, weekday: 770, weekend: 990 },
    ],
    charges: { single: 1100, entry: 550 },
  },
  nagoya_nishiki: {
    slug: "nagoya_nishiki",
    sourceUrl: "https://oriental-lounge.com/stores/25",
    // 2026-07-08 生HTML再確認: 平日18時〜06時、週末18時〜07時（週末は1時間遅い）。
    // 価格表は両曜日で同じ「24時〜Close」バンドを共有（専用バンド行は無い）。
    openH: 18,
    closeH: 6,
    closeHWeekend: 7,
    soloRate: { weekday: 220, weekend: 330 },
    bands: [
      { label: "Open〜20時", startH: 18, endH: 20, weekday: 550, weekend: 770 },
      { label: "20時〜22時", startH: 20, endH: 22, weekday: 660, weekend: 880 },
      { label: "22時〜24時", startH: 22, endH: 24, weekday: 770, weekend: 1100 },
      { label: "24時〜Close", startH: 24, endH: 30, weekday: 880, weekend: 1200 },
    ],
    charges: { single: 1100, entry: 550 },
  },
  nagoya_sakae: {
    slug: "nagoya_sakae",
    sourceUrl: "https://oriental-lounge.com/stores/8",
    openH: 17,
    closeH: 5,
    soloRate: { weekday: 220, weekend: 330 },
    bands: [
      { label: "Open〜20時", startH: 17, endH: 20, weekday: 600, weekend: 770 },
      { label: "20時〜22時", startH: 20, endH: 22, weekday: 660, weekend: 880 },
      { label: "22時〜24時", startH: 22, endH: 24, weekday: 700, weekend: 880 },
      { label: "24時〜Close", startH: 24, endH: 29, weekday: 770, weekend: 990 },
    ],
    charges: { single: 1100, entry: 550 },
  },
  namba: {
    slug: "namba",
    sourceUrl: "https://oriental-lounge.com/stores/12",
    openH: 19,
    closeH: 6,
    soloRate: { weekday: 220, weekend: 220 },
    bands: [
      { label: "Open〜20時", startH: 19, endH: 20, weekday: 660, weekend: 770 },
      { label: "20時〜22時", startH: 20, endH: 22, weekday: 660, weekend: 770 },
      { label: "22時〜24時", startH: 22, endH: 24, weekday: 770, weekend: 880 },
      { label: "24時〜Close", startH: 24, endH: 30, weekday: 770, weekend: 880 },
    ],
    charges: { single: 1100, entry: 550 },
  },
  oita: {
    slug: "oita",
    sourceUrl: "https://oriental-lounge.com/stores/40",
    openH: 18,
    closeH: 6,
    soloRate: { weekday: 220, weekend: 220 },
    bands: [
      { label: "Open〜20時", startH: 18, endH: 20, weekday: 550, weekend: 660 },
      { label: "20時〜22時", startH: 20, endH: 22, weekday: 550, weekend: 660 },
      { label: "22時〜24時", startH: 22, endH: 24, weekday: 660, weekend: 770 },
      { label: "24時〜Close", startH: 24, endH: 30, weekday: 660, weekend: 770 },
    ],
    charges: { single: 1100, entry: 550 },
  },
  okayama: {
    slug: "okayama",
    sourceUrl: "https://oriental-lounge.com/stores/29",
    openH: 18,
    closeH: 6,
    soloRate: { weekday: 220, weekend: 220 },
    bands: [
      { label: "Open〜20時", startH: 18, endH: 20, weekday: 500, weekend: 600 },
      { label: "20時〜22時", startH: 20, endH: 22, weekday: 600, weekend: 700 },
      { label: "22時〜24時", startH: 22, endH: 24, weekday: 660, weekend: 770 },
      { label: "24時〜Close", startH: 24, endH: 30, weekday: 770, weekend: 880 },
    ],
    charges: { single: 1100, entry: 550 },
  },
  okinawa_ag: {
    slug: "okinawa_ag",
    sourceUrl: "https://oriental-lounge.com/stores/20",
    openH: 18,
    closeH: 7,
    soloRate: { weekday: 330, weekend: 330 },
    bands: [
      { label: "Open〜20時", startH: 18, endH: 20, weekday: 660, weekend: 660 },
      { label: "20時〜22時", startH: 20, endH: 22, weekday: 660, weekend: 660 },
      { label: "22時〜24時", startH: 22, endH: 24, weekday: 770, weekend: 770 },
      { label: "24時〜Close", startH: 24, endH: 31, weekday: 880, weekend: 880 },
    ],
    charges: { single: 1100, entry: 550 },
  },
  omiya: {
    slug: "omiya",
    sourceUrl: "https://oriental-lounge.com/stores/24",
    openH: 18,
    closeH: 6,
    soloRate: { weekday: 220, weekend: 220 },
    bands: [
      { label: "Open〜20時", startH: 18, endH: 20, weekday: 550, weekend: 660 },
      { label: "20時〜22時", startH: 20, endH: 22, weekday: 660, weekend: 770 },
      { label: "22時〜24時", startH: 22, endH: 24, weekday: 660, weekend: 880 },
      { label: "24時〜Close", startH: 24, endH: 30, weekday: 770, weekend: 990 },
    ],
    charges: { single: 1100, entry: 550 },
  },
  osaka_ekimae: {
    slug: "osaka_ekimae",
    sourceUrl: "https://oriental-lounge.com/stores/41",
    // 2026-07-08 生HTML再確認: 平日18時〜06時、週末18時〜07時（週末は1時間遅い）。
    // 価格表は両曜日で同じ「24時〜Close」バンドを共有（専用バンド行は無い）。
    openH: 18,
    closeH: 6,
    closeHWeekend: 7,
    soloRate: { weekday: 330, weekend: 330 },
    bands: [
      { label: "Open〜20時", startH: 18, endH: 20, weekday: 700, weekend: 800 },
      { label: "20時〜22時", startH: 20, endH: 22, weekday: 700, weekend: 800 },
      { label: "22時〜24時", startH: 22, endH: 24, weekday: 880, weekend: 990 },
      { label: "24時〜Close", startH: 24, endH: 30, weekday: 880, weekend: 990 },
    ],
    charges: { single: 1100, entry: 550 },
  },
  sendai_ag: {
    slug: "sendai_ag",
    sourceUrl: "https://oriental-lounge.com/stores/2",
    openH: 18,
    closeH: 5,
    soloRate: { weekday: 220, weekend: 220 },
    bands: [
      { label: "Open〜20時", startH: 18, endH: 20, weekday: 550, weekend: 700 },
      { label: "20時〜22時", startH: 20, endH: 22, weekday: 600, weekend: 750 },
      { label: "22時〜24時", startH: 22, endH: 24, weekday: 700, weekend: 750 },
      { label: "24時〜Close", startH: 24, endH: 29, weekday: 770, weekend: 990 },
    ],
    charges: { single: 1100, entry: 550 },
  },
  shibuya: {
    slug: "shibuya",
    sourceUrl: "https://oriental-lounge.com/stores/4",
    openH: 18,
    closeH: 5,
    closeHWeekend: 7,
    soloRate: { weekday: 330, weekend: 330 },
    // 注意: 平日は 18:00〜05:00、週末は 18:00〜07:00 と閉店時刻自体が曜日で異なる
    // （2026-07-08 生HTML再確認: 営業時間セクションに明記）。公式の価格表は
    // 「24時〜6時」（両曜日共通）と「6時〜Close」（週末専用・平日は「-」表記）に
    // 分かれており、その通りに weekday:null で表現する。
    // データ修正メモ: 初回スクレイプでは「6時〜Close」の endH が 29（=翌05:00）で
    // 記録されていたが、これは自身の startH:6（=翌06:00）より前になり時系列として
    // 矛盾する（隣の「24時〜6時」バンドの endH をコピーした際の誤りと推定）。
    // 週末の実際の閉店が07:00（=31:00）であることを2026-07-08に生HTML再確認した
    // ため、このバンドの endH は 31 に補正済み（このロールアウト作業内で修正）。
    bands: [
      { label: "Open〜20時", startH: 18, endH: 20, weekday: 550, weekend: 770 },
      { label: "20時〜22時", startH: 20, endH: 22, weekday: 660, weekend: 880 },
      { label: "22時〜24時", startH: 22, endH: 24, weekday: 770, weekend: 1100 },
      { label: "24時〜6時", startH: 24, endH: 30, weekday: 880, weekend: 1200 },
      { label: "6時〜Close", startH: 6, endH: 31, weekday: null, weekend: 1200 },
    ],
    charges: { single: 1100, entry: 550 },
  },
  shibuya_ag: {
    slug: "shibuya_ag",
    sourceUrl: "https://oriental-lounge.com/stores/27",
    // 2026-07-08 生HTML再確認: 平日19時〜04時、週末19時〜05時（週末は1時間遅い）。
    // 価格表は両曜日で同じ「24時〜Close」バンドを共有（専用バンド行は無い）。
    openH: 19,
    closeH: 4,
    closeHWeekend: 5,
    soloRate: { weekday: 330, weekend: 330 },
    bands: [
      { label: "Open〜20時", startH: 19, endH: 20, weekday: 440, weekend: 660 },
      { label: "20時〜22時", startH: 20, endH: 22, weekday: 550, weekend: 770 },
      { label: "22時〜24時", startH: 22, endH: 24, weekday: 660, weekend: 990 },
      { label: "24時〜Close", startH: 24, endH: 28, weekday: 770, weekend: 990 },
    ],
    charges: { single: 1100, entry: 550 },
  },
  shinjuku: {
    slug: "shinjuku",
    sourceUrl: "https://oriental-lounge.com/stores/3",
    openH: 19,
    closeH: 5,
    soloRate: { weekday: 330, weekend: 330 },
    bands: [
      { label: "Open〜20時", startH: 19, endH: 20, weekday: 550, weekend: 660 },
      { label: "20時〜22時", startH: 20, endH: 22, weekday: 660, weekend: 770 },
      { label: "22時〜24時", startH: 22, endH: 24, weekday: 770, weekend: 880 },
      { label: "24時〜Close", startH: 24, endH: 29, weekday: 770, weekend: 990 },
    ],
    charges: { single: 1100, entry: 550 },
  },
  shinsaibashi: {
    slug: "shinsaibashi",
    sourceUrl: "https://oriental-lounge.com/stores/11",
    openH: 18,
    closeH: 5,
    soloRate: { weekday: 220, weekend: 330 },
    bands: [
      { label: "Open〜20時", startH: 18, endH: 20, weekday: 600, weekend: 660 },
      { label: "20時〜22時", startH: 20, endH: 22, weekday: 660, weekend: 770 },
      { label: "22時〜24時", startH: 22, endH: 24, weekday: 660, weekend: 770 },
      { label: "24時〜Close", startH: 24, endH: 29, weekday: 770, weekend: 880 },
    ],
    charges: { single: 1100, entry: 550 },
  },
  shizuoka: {
    slug: "shizuoka",
    sourceUrl: "https://oriental-lounge.com/stores/7",
    openH: 18,
    closeH: 6,
    soloRate: { weekday: 220, weekend: 220 },
    bands: [
      { label: "Open〜20時", startH: 18, endH: 20, weekday: 440, weekend: 550 },
      { label: "20時〜22時", startH: 20, endH: 22, weekday: 550, weekend: 660 },
      { label: "22時〜24時", startH: 22, endH: 24, weekday: 660, weekend: 880 },
      { label: "24時〜Close", startH: 24, endH: 30, weekday: 660, weekend: 880 },
    ],
    charges: { single: 1100, entry: 550 },
  },
  takasaki: {
    slug: "takasaki",
    sourceUrl: "https://oriental-lounge.com/stores/37",
    openH: 19,
    closeH: 5,
    soloRate: { weekday: 220, weekend: 220 },
    bands: [
      { label: "Open〜20時", startH: 19, endH: 20, weekday: 440, weekend: 550 },
      { label: "20時〜22時", startH: 20, endH: 22, weekday: 550, weekend: 660 },
      { label: "22時〜24時", startH: 22, endH: 24, weekday: 660, weekend: 770 },
      { label: "24時〜Close", startH: 24, endH: 29, weekday: 770, weekend: 880 },
    ],
    charges: { single: 1100, entry: 550 },
  },
  tenma: {
    slug: "tenma",
    sourceUrl: "https://oriental-lounge.com/stores/39",
    // データ修正メモ: 初回スクレイプでは closeH=6 だったが、2026-07-08 に生HTMLの
    // 「営業時間」セクションを再確認したところ、平日・週末とも実際の閉店は
    // 05:00（=29:00）であり、価格表の「24時〜Close」バンドの endH も 30(06:00)
    // ではなく 29(05:00) が正しい。また週末は17時開店（平日は18時開店）。
    openH: 18,
    closeH: 5,
    openHWeekend: 17,
    soloRate: { weekday: 330, weekend: 330 },
    bands: [
      { label: "Open〜20時", startH: 18, endH: 20, weekday: 600, weekend: 700 },
      { label: "20時〜22時", startH: 20, endH: 22, weekday: 600, weekend: 700 },
      { label: "22時〜24時", startH: 22, endH: 24, weekday: 770, weekend: 880 },
      { label: "24時〜Close", startH: 24, endH: 29, weekday: 770, weekend: 880 },
    ],
    charges: { single: 1100, entry: 550 },
  },
  ueno: {
    slug: "ueno",
    sourceUrl: "https://oriental-lounge.com/stores/33",
    // 2026-07-08 生HTML再確認: 平日18時〜01時、週末18時〜05時（週末は4時間遅い）。
    // 価格表は両曜日で同じ「24時〜Close」バンドを共有（専用バンド行は無い）。
    openH: 18,
    closeH: 1,
    closeHWeekend: 5,
    soloRate: { weekday: 330, weekend: 330 },
    bands: [
      { label: "Open〜20時", startH: 18, endH: 20, weekday: 550, weekend: 770 },
      { label: "20時〜22時", startH: 20, endH: 22, weekday: 660, weekend: 880 },
      { label: "22時〜24時", startH: 22, endH: 24, weekday: 770, weekend: 990 },
      { label: "24時〜Close", startH: 24, endH: 25, weekday: 880, weekend: 990 },
    ],
    charges: { single: 1100, entry: 550 },
  },
  ueno_ag: {
    slug: "ueno_ag",
    sourceUrl: "https://oriental-lounge.com/stores/28",
    // 2026-07-08 生HTML再確認: 平日18時〜05時、週末18時〜06時（週末は1時間遅い）。
    // 価格表は両曜日で同じ「24時〜Close」バンドを共有（専用バンド行は無い）。
    openH: 18,
    closeH: 5,
    closeHWeekend: 6,
    soloRate: { weekday: 330, weekend: 330 },
    bands: [
      { label: "Open〜20時", startH: 18, endH: 20, weekday: 550, weekend: 770 },
      { label: "20時〜22時", startH: 20, endH: 22, weekday: 660, weekend: 880 },
      { label: "22時〜24時", startH: 22, endH: 24, weekday: 770, weekend: 990 },
      { label: "24時〜Close", startH: 24, endH: 29, weekday: 880, weekend: 990 },
    ],
    charges: { single: 1100, entry: 550 },
  },
  umeda_ag: {
    slug: "umeda_ag",
    sourceUrl: "https://oriental-lounge.com/stores/10",
    openH: 17,
    closeH: 5,
    soloRate: { weekday: 330, weekend: 330 },
    bands: [
      { label: "Open〜20時", startH: 17, endH: 20, weekday: 660, weekend: 770 },
      { label: "20時〜22時", startH: 20, endH: 22, weekday: 660, weekend: 770 },
      { label: "22時〜24時", startH: 22, endH: 24, weekday: 770, weekend: 880 },
      { label: "24時〜Close", startH: 24, endH: 29, weekday: 770, weekend: 880 },
    ],
    charges: { single: 1100, entry: 550 },
  },
  utsunomiya: {
    slug: "utsunomiya",
    sourceUrl: "https://oriental-lounge.com/stores/26",
    // 2026-07-08 生HTML再確認: 平日19時〜04時、週末19時〜05時（週末は1時間遅い）。
    // 価格表は両曜日で同じ「24時〜Close」バンドを共有（専用バンド行は無い）。
    openH: 19,
    closeH: 4,
    closeHWeekend: 5,
    soloRate: { weekday: 220, weekend: 220 },
    bands: [
      { label: "Open〜20時", startH: 19, endH: 20, weekday: 440, weekend: 550 },
      { label: "20時〜22時", startH: 20, endH: 22, weekday: 550, weekend: 660 },
      { label: "22時〜24時", startH: 22, endH: 24, weekday: 660, weekend: 770 },
      { label: "24時〜Close", startH: 24, endH: 28, weekday: 770, weekend: 880 },
    ],
    charges: { single: 1100, entry: 550 },
  },
  yokohama: {
    slug: "yokohama",
    sourceUrl: "https://oriental-lounge.com/stores/23",
    openH: 18,
    closeH: 5,
    soloRate: { weekday: 330, weekend: 330 },
    bands: [
      { label: "Open〜20時", startH: 18, endH: 20, weekday: 550, weekend: 660 },
      { label: "20時〜22時", startH: 20, endH: 22, weekday: 660, weekend: 880 },
      { label: "22時〜24時", startH: 22, endH: 24, weekday: 770, weekend: 990 },
      { label: "24時〜Close", startH: 24, endH: 29, weekday: 880, weekend: 1100 },
    ],
    charges: { single: 1100, entry: 550 },
  },
};
