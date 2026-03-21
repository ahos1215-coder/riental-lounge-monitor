# MEGRIBI Blog Pipeline（LINE / Next.js / GitHub Actions / Supabase / GitHub）

最終更新: 2026-03-21

## 配管の全体像（結論）
- 司令塔（下書き）: Next.js `POST /api/line`（LINE Messaging Webhook 直受け）
- 司令塔（従来・任意）: n8n（セルフホスト）— 廃止または併用は運用次第
- 工場: GitHub Actions（実行環境）
- 資産: Supabase（Facts完全版 / `blog_drafts`） / GitHub（記事・画像・公開Facts）
- 承認: あなた（PRを見てマージ＝公開許可）

## 役割
- あなた：最終承認（PRマージ）
- LINE：指示UI（スマホ）
- Next.js：Webhook 受信 → Flask `/api/range` 等で材料取得 → Gemini で MDX 下書き → Supabase `blog_drafts` 保存 → LINE 返信
- n8n：（レガシー）受付・分岐・通知・再実行・ジョブ状態管理
- GitHub Actions：集計/診断/文章化/成果物生成・PR作成
- Supabase：元データ（logs）とFacts完全版、ジョブ状態、`blog_drafts`
- GitHub：成果物置き場（MDX/画像/公開Facts）＋承認ゲート（PR）

## 推奨フロー（MVP）
1) 指示（人が動かすのはここだけ）
- LINE → Next.js `/api/line`（Webhook）
- （任意・旧）LINE → n8n（Webhook）→ Supabase に job 作成（queued）

2) 工場稼働（自動）
- n8n → GitHub Actions 起動（job_id, store, topic, level）

3) 分析（Actions 内で3層）
A) 集計（計算・材料づくり）＝コード
- Supabase logs 取得 → 指標算出（ピーク帯、欠損率、直近変化など）

B) 診断（意味づけ）＝コード＋必要ならLLM補助
- ルールでラベル（安定/荒れ、急増、今日は読みやすい等）
- LLMは翻訳補助。根拠はFacts限定（幻覚対策）

C) 文章化（Render）＝LLM
- 骨格テンプレ＋言い換え辞書＋level制約
- X用文案も生成（まずはコピペ運用）

4) 資産化（確定）
- Supabase：Facts完全版を保存
- GitHub：公開して良い最小Facts（facts.json）＋記事MDX＋画像（あれば）
- GitHub：PR作成（勝手に公開しない）

5) 通知〜承認（半自動の肝）
- n8n → LINE通知（PRリンク/要点/注意/X文案）
- あなた → PR確認 → マージ（公開）

## 公開Facts生成（ローカル）
- MDX frontmatter の date/store/facts_id から夜窓（19:00-翌05:00 JST）を計算し、insight を自動生成する。
- 実行場所は repo root / `frontend` どちらでも可（`content/blog` を自動検出）。
- `/api/range?store=...&limit=1000` を優先し、窓内が空なら `/api/forecast_today` を使う。forecast の日付ズレは +1日シフトで救済する。

```powershell
cd frontend
npm run facts:generate -- --slug shibuya-tonight-20251221 --backend http://127.0.0.1:5000
```
