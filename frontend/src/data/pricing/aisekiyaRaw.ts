// frontend/src/data/pricing/aisekiyaRaw.ts
//
// 相席屋（brand="aisekiya"）の営業中5店舗（渋谷・池袋東口・上野・千葉中央・
// 横浜西口）の公式料金の生データ。オリエンタルラウンジとは別チェーンのため
// raw.ts とはファイルを分けている（曜日区分ルールも異なる。下記コメント参照）。
//
// 検証日: 2026-07-08。各店舗の公式ページ（https://aiseki-ya.com/shop/<slug>/）の
// 生HTMLを直接取得し、料金カード（`p-priceSystem` セクション内の
// `.c-priceCard__term` / `.c-priceCard__price` / `.c-priceCard__free`）と
// 「営業時間」セクション（`.p-storeDetail__data` の dt="営業時間"）の両方を
// 直接パースして転記した（build.ts 冒頭のコメントの通り、要約AI経由の
// WebFetch は同じページに対して複数回異なる集計結果を返すことがあるため、
// WebFetch の結果は一次情報としては使わず、生HTMLでの再確認を必須にしている）。
//
// ■ チェーン共通の料金モデル（5店舗全てで確認。例外・注記は下記参照）
//   相席していない時: 男性 無料（¥0）
//   相席時（22:00より前）: 月〜木曜日 ¥650（税込¥715）/10分、金〜日曜日・祝日・
//           祝前日 ¥750（税込¥825）/10分。
//   チャージ: ¥550（税込¥605）/1名。
//   女性: 完全無料（食べ飲み放題込み、チャージ料金も無し）。
//   ⚠️ 22時以降の深夜/サービス料10%加算: 5店舗**全店**の価格表に「※22時以降は、
//      深夜料金として10％加算させていただきます」（ay_shibuya/ay_ikebukuro/
//      ay_ueno/ay_chibaは全て同一文言で生HTML確認済み）、または同義の
//      「※22時以降の入店された場合は、サービス料10％が加算されます」
//      （ay_yokohamaのみ表現が異なるが同じ10%加算の趣旨）が明記されている。
//      つまり相席屋も「22:00を境に相席単価が上がる」2段階料金であり、オリエンタル
//      ほど細かい時間帯バンドは無いが「フラット単価」でもない。この加算は
//      computeAisekiyaStayCost が本体金額に反映し（¥650→¥715、¥750→¥825）、UIも
//      オリエンタルと同じ「値上がり注意行」で表示する。
//      検証当初は千葉店だけの店舗固有ルールと誤認し、かつ加算を注記のみで本体
//      金額に反映していなかった（22:00をまたぐ滞在で金額が過小表示になる不整合が
//      あった）。2026-07-08の作業で全店共通と判明し、加算を計算に組み込む形へ
//      修正した。
//
// ■ 曜日区分ルールがオリエンタルと異なる点（重要）
//   相席屋の「高単価（=weekend）」対象日は「金・土・日曜日・祝日・祝前日」。
//   オリエンタルの週末判定（金・土・祝前日、日曜含まず）とは異なり日曜日を含む。
//   このため jpHolidays.ts に相席屋専用の detectAisekiyaDayTypeJst を追加し、
//   オリエンタル用の detectDayTypeJst とは別関数にしている（既存関数は無改変）。
//
// ■ 店舗ごとの例外・注記
//   - 22時以降の10%加算（全店共通）: 各10分ユニットの開始時刻が22:00以降なら
//     単価に×1.1を適用して合算する（円未満四捨五入）。lateNightSurchargePct /
//     lateNightSurchargeFromH を全店舗データに加算ルールの根拠として保持する。
//     計算の実体は computeCost.ts の computeAisekiyaStayCost、表示は
//     CostSimulatorCard.tsx の「22:00以降は10分¥715（週末¥825）に上がります」行。
//   - ay_chiba のチャージ無料化は「LINE@登録」（他店の「アプリパスポート」とは
//     別の手段）。UIの「アプリチェックイン」トグルの文言と厳密には一致しないため、
//     店舗データに appWaiverLabel を持たせて表示文言を店舗ごとに出し分ける。
//   - ay_ikebukuro / ay_yokohama: 生HTMLにチャージ無料化の手段（アプリ/LINE等）の
//     記載が無い（=無条件で¥550）。appWaiverLabel は null。
//   - 営業時間は日毎にかなり細かく分かれている店舗がある（ay_ikebukuro,
//     ay_ueno）。PricingTableBase は weekday/weekend の二値でしか営業時間を
//     持てないため、相席屋の曜日区分（金・土・日・祝日・祝前日=weekend）に
//     沿って「その区分に属する曜日の中で最も広い範囲（最早openH・最遅closeH）」
//     を weekend 側の値として採用する（オリエンタルの raw.ts が
//     openHWeekend/closeHWeekend で「両曜日タイプのうち早い/遅い方」を採用する
//     のと同じ考え方の一般化）。各店舗のコメントに実際の曜日別内訳を残す。
//
// ■ 新潟万代店（旧 ay_niigata）について
//   2026-06-28に閉店。オーナー方針によりサイトから完全に削除する対象のため、
//   本ファイルには一切登場しない（RAW_AISEKIYA_PRICING に収録しない）。
//   ※ stores.json 及び Python バックエンド（multi_collect.py 等）からの削除は
//     SSOT・収集/予測/週次に横断的に影響するため、本フロントエンド料金タスクの
//     スコープ外。別途調整して削除すること（この注記は完了後に削除してよい）。

export type AisekiyaRawStorePricing = {
  slug: string;
  sourceUrl: string;
  /** 平日（月〜木）の開店時刻（24h表記） */
  openH: number;
  /** 平日（月〜木）の閉店時刻（24h表記、翌日側） */
  closeH: number;
  /** 高単価区分（金・土・日・祝日・祝前日）の開店時刻。区分内で最も早い値。 */
  openHWeekend: number;
  /** 高単価区分（金・土・日・祝日・祝前日）の閉店時刻。区分内で最も遅い値。 */
  closeHWeekend: number;
  /** 相席時10分単価（税抜・曜日タイプ別） */
  josekiRate: { weekday: number; weekend: number };
  /** 相席時10分単価・税込参考値 */
  josekiRateTaxIncluded: { weekday: number; weekend: number };
  /** チャージ（円・税抜） */
  chargeEntry: number;
  /** チャージ無料化の手段の表示ラベル。手段の記載が無い店舗は null（=無条件でチャージ発生） */
  appWaiverLabel: string | null;
  /** 深夜割増（%）。記載が無い店舗は undefined（=割増なし） */
  lateNightSurchargePct?: number;
  /** 深夜割増の適用開始時刻（24h表記）。lateNightSurchargePct 指定時のみ意味を持つ */
  lateNightSurchargeFromH?: number;
  /** この店舗データについての注記（UIフッターに表示） */
  assumptionNotes?: string[];
};

export const AISEKIYA_PRICING_VERIFIED_AT = "2026-07-08";

/** チェーン共通の相席時単価（6店舗全店がこの通り） */
const CHAIN_JOSEKI_RATE = { weekday: 650, weekend: 750 };
const CHAIN_JOSEKI_RATE_TAX_INCLUDED = { weekday: 715, weekend: 825 };
const CHAIN_CHARGE_ENTRY = 550;

// 注: 22時以降10%加算は「注記だけ」ではなく計算エンジン（computeAisekiyaStayCost）
// で本体金額に反映するよう修正済み。UIでもオリエンタルと同じ「値上がり注意行」
// （22:00以降は10分¥715/¥825に上がります）として表示する。そのため以前ここにあった
// 受動的な assumptionNote（「本シミュレーターの金額は加算を含めていません」）は
// 各店舗から削除した（金額に反映済みなので不要かつ誤りになるため）。
// lateNightSurchargePct/lateNightSurchargeFromH は加算ルールの根拠データとして残す
// （生HTMLで全店確認: 全店 22:00 から 10%。yokohamaのみ表現が「サービス料」だが同率同時刻）。

export const RAW_AISEKIYA_PRICING: Record<string, AisekiyaRawStorePricing> = {
  ay_shibuya: {
    slug: "ay_shibuya",
    sourceUrl: "https://aiseki-ya.com/shop/shibuya2/",
    // 生HTML確認: 月〜木・金・土・日/祝日・祝前日のいずれも "17:00-29:00" で統一
    // （店舗情報セクションに5行あるが全て同一値）。
    openH: 17,
    closeH: 29,
    openHWeekend: 17,
    closeHWeekend: 29,
    josekiRate: CHAIN_JOSEKI_RATE,
    josekiRateTaxIncluded: CHAIN_JOSEKI_RATE_TAX_INCLUDED,
    chargeEntry: CHAIN_CHARGE_ENTRY,
    appWaiverLabel: "アプリパスポート",
    // 生HTML確認: 「※22時以降は、深夜料金として10％加算させていただきます」
    // （加算は computeAisekiyaStayCost で本体金額に反映・UIの値上がり注意行で表示）
    lateNightSurchargePct: 10,
    lateNightSurchargeFromH: 22,
  },
  ay_ikebukuro: {
    slug: "ay_ikebukuro",
    sourceUrl: "https://aiseki-ya.com/shop/ikebukurohigashiguchi/",
    // 生HTML確認（営業時間セクション）:
    //   月〜木曜日：18:00-26:00(翌2:00)
    //   金曜日/祝前日：18:00-29:00(翌5:00)
    //   土曜日：17:00-29:00(翌5:00)
    //   日曜日/祝日：17:00-26:00(翌2:00)
    // 相席屋の高単価区分（金・土・日・祝日・祝前日）内で最も早い開店=17:00(土/日)、
    // 最も遅い閉店=29:00(金/土)を weekend 側の代表値として採用。
    openH: 18,
    closeH: 26,
    openHWeekend: 17,
    closeHWeekend: 29,
    josekiRate: CHAIN_JOSEKI_RATE,
    josekiRateTaxIncluded: CHAIN_JOSEKI_RATE_TAX_INCLUDED,
    chargeEntry: CHAIN_CHARGE_ENTRY,
    // 生HTML確認: チャージ無料化の手段（アプリパスポート等）の記載が無い
    appWaiverLabel: null,
    // 生HTML確認: 「※22時以降は、深夜料金として10％加算させていただきます」
    // （加算は computeAisekiyaStayCost で本体金額に反映・UIの値上がり注意行で表示）
    lateNightSurchargePct: 10,
    lateNightSurchargeFromH: 22,
    assumptionNotes: [
      "営業時間は曜日ごとに細かく異なります（月〜木18:00〜翌2:00、金・祝前日18:00〜翌5:00、土17:00〜翌5:00、日・祝日17:00〜翌2:00）。本シミュレーターは「平日/週末」の2区分表示のため、週末側は区分内で最も広い範囲（17:00〜翌5:00）で表示しています。詳細は公式サイトでご確認ください。",
    ],
  },
  ay_ueno: {
    slug: "ay_ueno",
    sourceUrl: "https://aiseki-ya.com/shop/ueno/",
    // 生HTML確認（営業時間セクション）:
    //   (月~木) 17:00-27:00
    //   (金) 17:00-29:00
    //   (土) 15:00-29:00
    //   (日/祝日) 15:00-27:00
    //   (祝前日) 17:00-29:00
    // 高単価区分内で最も早い開店=15:00(土/日)、最も遅い閉店=29:00(金/土/祝前日)。
    openH: 17,
    closeH: 27,
    openHWeekend: 15,
    closeHWeekend: 29,
    josekiRate: CHAIN_JOSEKI_RATE,
    josekiRateTaxIncluded: CHAIN_JOSEKI_RATE_TAX_INCLUDED,
    chargeEntry: CHAIN_CHARGE_ENTRY,
    appWaiverLabel: "アプリパスポート",
    // 生HTML確認: 「※22時以降は、深夜料金として10％加算させていただきます」
    // （加算は computeAisekiyaStayCost で本体金額に反映・UIの値上がり注意行で表示）
    lateNightSurchargePct: 10,
    lateNightSurchargeFromH: 22,
    assumptionNotes: [
      "営業時間は曜日ごとに細かく異なります（月〜木17:00〜翌3:00、金・祝前日17:00〜翌5:00、土15:00〜翌5:00、日・祝日15:00〜翌3:00）。本シミュレーターは「平日/週末」の2区分表示のため、週末側は区分内で最も広い範囲（15:00〜翌5:00）で表示しています。詳細は公式サイトでご確認ください。",
    ],
  },
  ay_chiba: {
    slug: "ay_chiba",
    sourceUrl: "https://aiseki-ya.com/shop/chibachuo/",
    // 生HTML確認（営業時間セクション）: 「日〜木曜日：18:00 - 翌0:00」
    // 「金〜土曜日：18:00 - 翌5:00」。営業時間の区分は「日〜木」対「金〜土」だが、
    // 相席屋チェーン共通の料金曜日区分（金・土・日・祝日・祝前日=高単価）では
    // 日曜日は高単価側に入る。つまり日曜日は「営業時間としては平日グループ
    // （18:00〜翌0:00）」だが「価格は週末（¥750）」という、営業時間区分と
    // 価格区分がズレる店舗（このシミュレーターの weekday/weekend 二値モデルでは
    // 「価格」区分を優先して weekend 側を金・土・日でまとめて扱うため、
    // 日曜日の実際の閉店が24:00である点は openHWeekend/closeHWeekend の代表値
    // （18:00〜翌5:00＝金土の値）に含めていない。assumptionNotes に明記する）。
    openH: 18,
    closeH: 24,
    openHWeekend: 18,
    closeHWeekend: 29,
    josekiRate: CHAIN_JOSEKI_RATE,
    josekiRateTaxIncluded: CHAIN_JOSEKI_RATE_TAX_INCLUDED,
    chargeEntry: CHAIN_CHARGE_ENTRY,
    // 生HTML確認: 「LINE@登録で無料になります。」（他店の「アプリパスポート」とは別手段）
    appWaiverLabel: "LINE@登録",
    // 生HTML確認: 「※22時以降は、深夜料金として10％加算させていただきます」（全店共通ルール）
    // （加算は computeAisekiyaStayCost で本体金額に反映・UIの値上がり注意行で表示）
    lateNightSurchargePct: 10,
    lateNightSurchargeFromH: 22,
    assumptionNotes: [
      "日曜日は営業時間としては18:00〜翌0:00（月〜木と同じ区分）ですが、料金は週末（金・土・日・祝日・祝前日）区分の¥750が適用されます。本シミュレーターの「週末」営業時間表示（18:00〜翌5:00）は金・土曜日の実際の営業時間です。日曜日の実際の閉店は翌0:00のため、日曜深夜の滞在計算では実際の閉店時刻と異なる場合があります。",
    ],
  },
  ay_yokohama: {
    slug: "ay_yokohama",
    sourceUrl: "https://aiseki-ya.com/shop/yokonishi/",
    // 生HTML確認（営業時間セクション）:
    //   (月~木) 18:00-29:00 / (金) 18:00-29:00 / (土) 17:00-29:00
    //   (日/祝日) 17:00-29:00 / (祝前日) 17:00-29:00
    // 高単価区分内で最も早い開店=17:00(土/日/祝前日)、最も遅い閉店=29:00（全日同じ）。
    openH: 18,
    closeH: 29,
    openHWeekend: 17,
    closeHWeekend: 29,
    josekiRate: CHAIN_JOSEKI_RATE,
    josekiRateTaxIncluded: CHAIN_JOSEKI_RATE_TAX_INCLUDED,
    chargeEntry: CHAIN_CHARGE_ENTRY,
    // 生HTML確認: 男性チャージ無料化の手段（アプリ/LINE等）の記載が無い。
    // 女性チャージ欄に「<!-- 500円（税込550円） -->」というコメントアウトされた
    // 未使用マークアップが残っているのみで、実際の料金表示には影響しない。
    appWaiverLabel: null,
    // 生HTML確認: 「※22時以降の入店された場合は、サービス料10％が加算されます」
    // （他店の「深夜料金」ではなく「サービス料」という表現だが同じ10%加算の趣旨。
    // 加算は computeAisekiyaStayCost で本体金額に反映・UIの値上がり注意行で表示）
    lateNightSurchargePct: 10,
    lateNightSurchargeFromH: 22,
  },
};
