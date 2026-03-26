# MEGRIBI コンテンツ戦略（2026-03-26 版）
Last updated: 2026-03-26
Target commit: (see git)

## コンテンツの分類（実装済み）

### 1. AI 予測予報（Daily Report）— 完全自動
- **概要**: 毎日 JST 18:00 / 21:30 に GitHub Actions が全 38 店舗分を自動生成・即時公開
- **URL**: `/reports/daily/[store_slug]`（固定 URL 上書き。過去分は Supabase にのみ保存）
- **SEO**: 店舗ごとに固定パスで鮮度（Freshness）を優先。カニバリゼーションなし
- **`content_type`**: `daily`
- **`is_published`**: 生成完了時に `true`（ユーザー操作不要）
- **運用**: 完全自動。失敗店舗は GHA 再実行で対応

### 2. AI 週次レポート（Weekly Report）— 完全自動
- **概要**: 毎週水曜 06:30 JST（UTC 火曜 21:30）に GitHub Actions が全 38 店舗分を自動生成・即時公開
- **URL**: `/reports/weekly/[store_slug]`（固定 URL 上書き）
- **内容**: Good Window 分析 + 占有率・男女比の時系列（`series_compact`）。`/insights/weekly/[store]` の Recharts 可視化とも連動
- **`content_type`**: `weekly`
- **`is_published`**: 生成完了時に `true`（自動）
- **運用**: 完全自動（Fan-in Matrix）

### 3. 編集ブログ記事（Editorial Blog）— 半自動（人間承認あり）
- **概要**: LINE でオーダーして AI が分析記事の下書きを生成。内容を確認後に LINE で承認・公開
- **URL**: `/blog/[slug]`（`public_slug` をパスに使用）
- **内容**: 店舗比較・月次トレンド・ML 分析結果など不定期の深い記事
- **`content_type`**: `editorial`
- **`is_published`**: 最初は `false`、LINE 承認後 `true`
- **運用**: オーダー → AI 下書き → 確認 → LINE で「公開」送信 → URL が届く

---

## 目的

- **SEO 流入を増やす**（夜遊び・相席系の検索需要）
- **Daily / Weekly**: 鮮度の高いコンテンツを自動で維持（人手ゼロ）
- **Editorial**: めぐりびの価値（店舗比較・混雑傾向・ML 分析）を読者向けに翻訳。半自動で継続運用できる仕組み（人が最終責任）
- 分析結果をブログ以外にも使い回せる形で資産化（二重管理しない）

---

## LINE 下書き（Editorial 運用手順）

1. LINE で「渋谷店の先週の特徴を分析して」等を送信
2. AI が下書きを生成 → 「確認してから『公開』と送ってください」返信
3. （確認して問題なければ）LINE で「公開」と送信
4. AI が `/blog/[slug]` で公開 → URL を返信
5. 修正が必要な場合は再度依頼（下書きを上書き）

**インテント例**（認識パターン）:
- `editorial_analysis` / `draft`: 「分析して」「レポート作って」「まとめて」
- `approve`: 「公開」「ok」「承認」「publish」

---

## Facts と Render の分離（変わらない方針）

- **Facts（内部資産）**: 数値・指標・傾向ラベル・欠損状況・注意点・対象期間
- **Render（外向け表現）**: 読者向け文章、構成、導入の人間味、注意書き

## 保存戦略（確定）

- **Supabase `blog_drafts`**: 下書きの完全版（日次/週次/編集すべて保存）
- **GitHub（`frontend/content/insights/weekly`）**: Weekly の JSON ファイル（静的表示・Recharts 用）
- **GitHub（`frontend/content/blog`）**: Editorial の MDX（`npm run drafts:export` でエクスポート後 PR・任意）
- 記事本文（Markdown/MDX）・画像は GitHub に保存（DB に溜めない）

---

## 表現ルール（合意・Editorial 向け）

- 表はやさしく、裏はガチ
- 行動に直結する結論
- 理由は基本1つ
- 数字は最小限
- レベル別出力（easy / normal / pro）
- 言い換え辞書でAI出力の癖を抑える（例: spike→急に増える）

## Editorial 記事テンプレ（骨格固定）

- タイトル：今夜の◯◯店、狙い目は◯時台
- 10秒まとめ（Factsから自動表示）
- 今日の一言（短い一文）
- 理由はこれ（根拠1つ）
- 初心者メモ（失敗しない動き方）
- くわしく（任意：グラフや注意点を隔離）

---

## リポジトリ内の配置

| コンテンツ | 場所 |
|-----------|------|
| Daily / Weekly | Supabase `blog_drafts`（メイン）|
| Weekly JSON（可視化用） | `frontend/content/insights/weekly/<store>/<date>.json` |
| Editorial MDX（任意エクスポート）| `frontend/content/blog/<facts_id>.mdx` |
| 公開 Facts（最小）| `frontend/content/facts/public/<facts_id>.json` |
| 画像 | `frontend/public/blog-assets/<slug>/` |
| テンプレ | `frontend/content/blog/_templates/_TEMPLATE.mdx` |

---

## 廃止した運用

- **`/blog/auto-[store]-[slot]` URL**: `/reports/daily/[store_slug]` に移行済み
- **`autoCards`（blog/page.tsx 内の自動更新カード表示）**: 削除済み。AI 予測レポートへの誘導バナーに置き換え
- **ブログページでの daily 下書き一覧表示**: `fetchLatestAutoBlogDrafts` は UI から除去済み
