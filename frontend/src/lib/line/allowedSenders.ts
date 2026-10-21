/**
 * LINE Webhook のコマンド（下書き生成・公開）を受け付ける送信者の許可リスト。
 *
 * 署名検証（x-line-signature）が証明するのは「LINE のサーバーから届いた」ことだけで、
 * 「オーナーが送った」ことではない。ボットを友だち追加した人なら誰でも署名付きのイベントを
 * 送れてしまい、自由文入りの記事生成や「公開」「<slug> を公開」が通っていたため、送信者の
 * userId でここを絞る（2026-10-22 セキュリティ点検）。
 *
 * 許可リスト = `LINE_ALLOWED_USER_IDS`（カンマ区切り）∪ `LINE_USER_ID`。
 * `LINE_USER_ID` は通知の送り先として既に使っているオーナーの ID を流用するため。グループ ID（C…）が
 * 入っていても userId（U…）とは一致しないので無害。
 * 本番・Preview で両方とも空なら誰も通さない（fail-closed）。`NODE_ENV=development` で空のときだけ
 * 全員通す（ローカル検証用。`SKIP_LINE_SIGNATURE_VERIFY` と同じ考え方）。
 */

type Env = Partial<Record<string, string | undefined>>;

export function parseAllowedLineUserIds(env: Env = process.env): Set<string> {
  const raw = [env.LINE_ALLOWED_USER_IDS ?? "", env.LINE_USER_ID ?? ""].join(",");
  return new Set(
    raw
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean),
  );
}

export function isAllowedLineSender(userId: string | null | undefined, env: Env = process.env): boolean {
  const allowed = parseAllowedLineUserIds(env);
  if (allowed.size === 0) return env.NODE_ENV === "development";
  return typeof userId === "string" && allowed.has(userId.trim());
}
