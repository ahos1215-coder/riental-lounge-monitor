# STATUS（定時ブログ Cron / 運用）

## 成功の定義（チーム共通）

- **GitHub Actions の緑／赤だけで「成功」とはみなさない。**
- **正本は Supabase `blog_drafts`** である。対象日付・店舗 slug の行を開き、次を確認する。
  - **`error_message` が null（または空）** で、意図した本文・メタが入っている → **その店舗・その日は成功**。
  - **`error_message` がある**、または行がない → **未完了または失敗**（再実行の候補）。
- Actions は **起動・並列実行・再試行のオーケストレーション**であり、ゲートウェイや `curl` の HTTP コードは補助情報に過ぎない。
- **matrix の一部失敗**は `continue-on-error` のためワークフロー全体が**緑**に見えることがある。**`OPS_NOTIFY_WEBHOOK_URL` を設定している場合**、失敗店舗 slug を列挙した **Slack/Discord 通知**が送られる。正本は変わらず **Supabase**。

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

## 定時 Cron 実行後のチェックリスト（初回・ワークフロー変更直後）

**いつ**: JST **18:00 便**または **21:30 便**の直後（もしくは **`workflow_dispatch`** で全店を手動実行した直後）。

1. **GitHub** → **Actions** → **Blog draft cron (GitHub Actions)** → いま完了した **run** を開く。
2. **ジョブ一覧**で次を確認する。
   - **`trigger`** が店舗ごとに並び、各店の `GET /api/cron/blog-draft` ステップが成功/失敗していること。
   - **`Summarize matrix results`** が **成功（緑）** であること。ここで API が各ジョブの結論を集計する。
   - **一部店舗だけ失敗**している場合: **`notify-partial-blog-failures`** が実行され、**`OPS_NOTIFY_WEBHOOK_URL` 設定時**は Slack/Discord に「問題のある店舗 slug」が載った通知が届くこと（届かない場合は Secret / Variable を確認）。**Summarize** は `continue-on-error` でジョブが緑でも **ステップ失敗**（`curl` 失敗・504 等）を GitHub API で検知する。
   - **全店成功**の場合: `notify-partial-blog-failures` は **条件によりスキップ**され、部分失敗通知は来ない（正常）。
3. **正本**: 上記のあと、必ず **Supabase `blog_drafts`** で対象日・各店の **`error_message`** と本文を確認する（手順は上記「監視の手順（最短）」）。
4. **部分失敗通知だけ来ない**のとき: **`OPS_NOTIFY_WEBHOOK_URL`** が未設定でないか確認する。同じ run で **GET ステップが赤**なのに通知が無い場合は、GitHub の matrix ジョブの表示名が **`trigger (店舗slug)`** 形式かどうかを確認する。形式が違う場合は `.github/workflows/trigger-blog-cron.yml` 内 `summarize-blog-matrix` の **正規表現**（`trigger (…)` のマッチ）を実名に合わせて修正する（詳細は `plan/BLOG_CRON_GHA.md`）。

## 将来：同期 HTTP の限界を超えるとき

504 が店舗単位でも再発し、45 秒バジェットや GHA 分割では足りない場合は、**202 Accepted＋バックグラウンド処理**や**キュー**の導入を検討する。選択肢と段階は **`plan/BLOG_CRON_ASYNC_FUTURE.md`** に記載する。
