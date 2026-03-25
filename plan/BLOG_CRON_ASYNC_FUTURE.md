# 定時ブログ：非同期化・キュー（将来の抜本案メモ）

Last updated: 2026-03-25

## いつ検討するか

- Vercel の **同期 HTTP** と **実行時間上限**の組み合わせで、**店舗単位でも** 504 / タイムアウトが再発し続けるとき。
- 生成パイプライン（バックエンド取得＋Gemini）が **45 秒バジェット**を常に超えるようになったとき。
- GitHub Actions の **並列ジョブ数**や再試行だけでは運用負荷が高いとき。

現状は **「1 店舗 = 1 GHA ジョブ」＋ API 内 45 秒ガード**で同期型のまま運用する。本ファイルは **ステップ 2〜3** の選択肢を整理したもので、未実装の設計メモである。

## ステップ 2：非同期 Webhook パターン（短期）

1. Actions または管理画面が `POST /api/cron/blog-draft/enqueue` のような **軽いエンドポイント**を叩く。
2. API は **すぐに 202 Accepted** と **ジョブ ID**（または `facts_id` 相当）を返す。
3. 実処理は **Vercel 以外**（Pro の Background Functions、別ワーカー、Supabase Edge Function 等）で実行し、完了時に Supabase `blog_drafts` を更新する。

**利点**: ゲートウェイの同期制限から切り離せる。**注意**: ワーカー常駐・デプロイ先・コストが増える。

## ステップ 3：キューイング（中長期）

- **Upstash QStash**、**Supabase pg_cron + Edge Functions**、**Cloud Tasks** 等に「店舗 slug + edition + 日付」を積む。
- Actions は **キュー投入だけ**にし、コンシューマが並列度・リトライ・デッドレターを担当する。
- **正本**は引き続き Supabase `blog_drafts`（`error_message`・更新時刻）とする。

## 移行時の不変条件

- **冪等性**: 同一 `facts_id`（店舗＋日付）の再実行は **upsert** で上書き可能であること。
- **監視**: HTTP ステータスだけでなく **`blog_drafts` の内容**で成功を判定する（`STATUS.md` / `plan/BLOG_CRON_GHA.md` と整合）。

## 関連ドキュメント

- `STATUS.md`（リポジトリ直下）：監視・再実行の運用
- `plan/BLOG_CRON_GHA.md`：GitHub Actions 正本
- `.github/workflows/trigger-blog-cron.yml` / `retry-blog-draft-stores.yml`
