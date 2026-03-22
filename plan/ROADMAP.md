# ROADMAP
Last updated: 2026-03-21
Target commit: (see git)

> **構想・フェーズ順・備忘の全文**は **`plan/VISION_AND_FUTURE.md`**。本ファイルは短いタスク一覧と「当面やらないこと」に絞る。

---

## P0（次に着手しやすい項目）
- **`avoid_time` / プロンプト**: `draftGenerator.ts` で「入店しやすさの目安」「提案型」を固定。ズレる場合は人手修正または微調整（`plan/VISION_AND_FUTURE.md` §9 も参照）。
- **`RANGE_LIMIT`**（`frontend/src/app/api/line/route.ts`）と **`BLOG_CRON_RANGE_LIMIT`**（定時 Cron）の妥当性（`limit` が小さいとインサイトが偏る）
- **Web フロント**: 新規の「土台作り」より **既存画面の改善・見せ方・コンテンツ拡充**（`VISION_AND_FUTURE.md` フェーズ A）
- 主要ドキュメントの継続同期（`plan/*` と README の整合）
- Weekly Insights の品質改善（score 閾値・最小継続時間の運用調整）
- `/api/current` の位置づけ見直し（Supabase 直取得に寄せるか、現状維持かを決定）

## P1
- 週次 Insights の可視化強化（series_compact の導入や説明文の追加）
- ブログ / Facts の運用負荷削減（テンプレ整理、入力バリデーション）
- 監視・運用の可視化（ログの整理、Render/Vercel 運用の整理）
- **GitHub Actions の失敗通知**（週次 Insights 等は `/api/range` 依存。Render スリープ・タイムアウトで黙って失敗しうる → メール/Slack 等で検知）
- **`POST /api/line` の防衛**: 署名検証の徹底、**レート制限**（Edge Middleware 等）の検討 — **Gemini コスト・悪用対策**（`plan/ADVISORY_SYNTHESIS.md`）
- **X（Twitter）API 連携・OGP・投稿ルート**（`VISION_AND_FUTURE.md` フェーズ B）— **未実装。構想段階**。自動投稿のスコープは **人気トップ5店＋長崎店のみ**から開始する方針（§9）。

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
- **Cron 制限（Vercel Hobby）**: 店舗数が増え Vercel の Cron 回数が足りなくなったら、**GitHub Actions から毎日 JST 18:00 / 21:30 に `GET /api/cron/blog-draft` を叩く**案へ移行を検討（複雑化しすぎない範囲で）。
- **X 自動投稿**: 全店舗一斉ポストは行わず、開始時は **人気トップ5＋長崎店**に限定（API・シャドウバンリスク回避）。

## 未実装メモ
- 定時ブログは `GET /api/cron/blog-draft`（`frontend/vercel.json`）で実装済み。39 店舗スケール時は上記 §9・Cron 移行案を参照。
