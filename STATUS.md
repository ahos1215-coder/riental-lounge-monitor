# STATUS（定時ブログ Cron / 運用）

## 成功の定義（チーム共通）

- **GitHub Actions の緑／赤だけで「成功」とはみなさない。**
- **正本は Supabase `blog_drafts`** である。対象日付・店舗 slug の行を開き、次を確認する。
  - **`error_message` が null（または空）** で、意図した本文・メタが入っている → **その店舗・その日は成功**。
  - **`error_message` がある**、または行がない → **未完了または失敗**（再実行の候補）。
- Actions は **起動・並列実行・再試行のオーケストレーション**であり、ゲートウェイや `curl` の HTTP コードは補助情報に過ぎない。

## 監視の手順（最短）

1. Supabase で `blog_drafts` を開く。
2. **対象日（JST）** と **店舗 slug** で絞り込む（必要なら `created_at` / `updated_at` も参照）。
3. 失敗・欠損店舗をメモし、下記「再実行」へ進む。

詳細は `plan/BLOG_CRON_GHA.md`、トラブルシュートは `plan/RUNBOOK.md` の定時ブログ節。

## 失敗店舗だけ再実行する（手動）

1. GitHub → **Actions** → **Retry blog draft (selected stores)** → **Run workflow**。
2. **edition** を、定時で出したい便と同じにする（`evening_preview` = 18 時便、`late_update` = 21:30 便）。
3. **stores** に、カンマ区切りで slug のみ（例: `nagasaki,fukuoka`）。空白は無視される。
4. 実行後、再度 **Supabase `blog_drafts`** で当該店舗を確認する。

全 38 店の定時実行は **Blog draft cron (GitHub Actions)**（`.github/workflows/trigger-blog-cron.yml`）のまま。

## 将来：同期 HTTP の限界を超えるとき

504 が店舗単位でも再発し、45 秒バジェットや GHA 分割では足りない場合は、**202 Accepted＋バックグラウンド処理**や**キュー**の導入を検討する。選択肢と段階は **`plan/BLOG_CRON_ASYNC_FUTURE.md`** に記載する。
