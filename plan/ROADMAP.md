# ROADMAP
Last updated: 2026-03-25
Target commit: (see git)

> **構想・フェーズ順・備忘の全文**は **`plan/VISION_AND_FUTURE.md`**。本ファイルは短いタスク一覧と「当面やらないこと」に絞る。

---

## P0（次に着手しやすい項目）
- **`avoid_time` / プロンプト**: `draftGenerator.ts` で「混雑が落ち着いている目安」「提案型」の表現を固定（**2026-03 10秒まとめ用ラベル追記済み**）。ズレる場合は人手修正または微調整（`plan/VISION_AND_FUTURE.md` §9 も参照）。
- **`LINE_RANGE_LIMIT` / `BLOG_CRON_RANGE_LIMIT`**: LINE は既定 **500**（`LINE_RANGE_LIMIT` で上書き可）。定時は **`BLOG_CRON_RANGE_LIMIT`**（既定 500）。運用で偏りがあれば両方を揃えて調整。
- **定時ブログのスケール（実装済みの前提）**: **`GET /api/cron/blog-draft` は 1 リクエスト = 1 店舗**（`?store=` 必須）。**GitHub Actions**（`trigger-blog-cron.yml`）が **店舗ごとに並列ジョブ**で叩き、API 内は **約 45 秒バジェット**。失敗店舗のみは **`retry-blog-draft-stores.yml`**。さらなる長時間化や 504 再発時は **`plan/BLOG_CRON_ASYNC_FUTURE.md`**。
- **Web フロント**: 新規の「土台作り」より **既存画面の改善・見せ方・コンテンツ拡充**（`VISION_AND_FUTURE.md` フェーズ A）。**進捗メモ**: `/`・`/store/[id]`・`/stores`・**`/mypage`（お気に入り・閲覧履歴・localStorage、`meguribiStorage.ts`）**・店舗ページのお気に入りトグル。残りはブログ周りの文言・細かな UI 等。
- 主要ドキュメントの継続同期（`plan/*` と README の整合）
- Weekly Insights の品質改善（score 閾値・最小継続時間の**運用調整**は引き続き。可視化は下記 P1 で実装済み）
- **`/api/current`**: **方針メモを `plan/API_CURRENT.md` に追記済み**（当面は Flask 実装維持）。Supabase 直取得へ寄せるかは別タスクで決定

## P1
- 週次 Insights の可視化強化（**実装済み**: `series_compact`＋`WeeklyStoreCharts.tsx`／`plan/WEEKLY_INSIGHTS_TUNING.md`。追加の系列や説明文は任意）
- ブログ / Facts の運用負荷削減（**frontmatter Zod 検証は実装済み** `blogFrontmatter.ts`。残り: テンプレ整理・Facts 側など）
- 監視・運用の可視化（ログの整理、Render/Vercel 運用の整理）
- **GitHub Actions の失敗通知**（**実装済み**: Secret `OPS_NOTIFY_WEBHOOK_URL` + 任意 Variable `OPS_NOTIFY_WEBHOOK_TYPE`。`plan/RUNBOOK.md` 参照。`blog-ci` は対象外）
- **`POST /api/line` の防衛**: 署名検証に加え **レート制限を実装済み**（グローバル＋ユーザー単位、Upstash 推奨。`plan/DECISIONS.md` 14 / `plan/ENV.md`）。追加で IP ベース Middleware 等が必要なら別検討（Webhook は LINE 経由のため IP は補助）
- **Gemini 出力の構造化**: frontmatter と本文の分離（JSON + text）を検証し、プロンプト変更時の MDX 破損耐性を強化。
- **OGP / メタデータ**（主要ページ・ブログ）— **実装済み**（`plan/STATUS.md`）。**X（Twitter）API 連携・投稿用 API ルート**（`VISION_AND_FUTURE.md` フェーズ B）— **未実装。構想段階**。自動投稿のスコープは **人気トップ5店＋長崎店のみ**から開始する方針（§9）。

## P2
- 複数店舗/ブランドの拡張（表示/UI の拡張）
- 予測の精度・運用（オンザフライ学習 vs 定期学習モデル等。`VISION_AND_FUTURE.md` フェーズ C）
- **PWA / Web Push**（フェーズ D）
- **Stripe・課金・プレミアム予測**（フェーズ E）— **外部助言: 個人開発では当面優先度を下げてよい**（`plan/ADVISORY_SYNTHESIS.md`）

## 当面やらない（方針）
- **PR の URL を LINE に自動送信する**仕組み（必要になったら設計から検討。**n8n は使わない**）。

## 将来オプション（仕様未定）
- **公開までフル自動**（環境変数 ON/OFF 等）。**ガードレール・Staging 前提**。`VISION_AND_FUTURE.md` §5。

## スケール・SEO・Cron（方針の要約・詳細は `VISION_AND_FUTURE.md` §9）
- **SEO（全店・1日2本）**: 店舗ごとの記事 URL は **同一 `facts_id` パスへの上書き**（`npm run drafts:export -- --force` 等）とし、**カニバリゼーションを避け鮮度（Freshness）**を優先。
- **定時ブログの時計**: **GitHub Actions**（`.github/workflows/trigger-blog-cron.yml`）が正本。`vercel.json` の Cron は **使わない**（二重実行防止のため削除済み）。Secrets・スケジュールは **`plan/BLOG_CRON_GHA.md`**。
- **Vercel Hobby の Cron**（参考）: 使わないが、各式は 1 日 1 回まで・実行時刻にブレがありやすい、などの制約は公式ドキュメント参照。
- **X 自動投稿**: 全店舗一斉ポストは行わず、開始時は **人気トップ5＋長崎店**に限定（API・シャドウバンリスク回避）。

## 未実装メモ
- 定時ブログは `GET /api/cron/blog-draft`（**GHA** から `GET` + `edition` / `source` + **`store` 必須**）で実装済み。全店は **matrix 並列**、非同期キューは **`plan/BLOG_CRON_ASYNC_FUTURE.md`**。
