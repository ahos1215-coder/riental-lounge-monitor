import { formatJstMonthDay, jstNightSessionDate } from "@/lib/dateFormat";

/**
 * 店舗ページの「最新デイリーレポート要約」カードの見出し文言。
 *
 * 日次レポートは同一 store_slug の最新行を上書きするため、翌日の昼に開いても
 * 前夜 21:30 に生成された記事がそのまま返る。それを常に「今日の傾向まとめ」と
 * 名乗ると「今はかなり賑わっている」等の前夜の記述が“今日”の話に見えてしまう。
 *
 * そこで記事の `target_date`（生成時刻の JST 日付＝その夜の日付）と、
 * 現在の夜セッション日付（00:00-05:59 は前夜扱いの -6h 規約）を突き合わせ、
 * ズレていれば「前回（M/D）の傾向まとめ」に変える。
 * 情報は消さずに（＝カードは出したまま）、嘘だけをやめる方針。
 */
export function buildLatestSummaryTitle(
  targetDate: string | undefined | null,
  now: Date = new Date(),
): string {
  const target = (targetDate ?? "").trim();
  const tonight = jstNightSessionDate(now);
  // 判定材料が欠けるときは従来どおりの見出し（判定不能で「前回」と決めつけない）
  if (!target || !tonight || target === tonight) return "今日の傾向まとめ";
  const label = formatJstMonthDay(target);
  return label ? `前回（${label}）の傾向まとめ` : "前回の傾向まとめ";
}
