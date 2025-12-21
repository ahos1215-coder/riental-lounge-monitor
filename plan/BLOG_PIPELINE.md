# MEGRIBI Blog Pipeline（n8n / GitHub Actions / Supabase / GitHub）

最終更新: 2025-12-20

## 配管の全体像（結論）
- 司令塔: n8n（セルフホスト）
- 工場: GitHub Actions（実行環境）
- 資産: Supabase（Facts完全版） / GitHub（記事・画像・公開Facts）
- 承認: あなた（PRを見てマージ＝公開許可）

## 役割
- あなた：最終承認（PRマージ）
- LINE：指示UI（スマホ）
- n8n：受付・分岐・通知・再実行・ジョブ状態管理
- GitHub Actions：集計/診断/文章化/成果物生成・PR作成
- Supabase：元データ（logs）とFacts完全版、ジョブ状態
- GitHub：成果物置き場（MDX/画像/公開Facts）＋承認ゲート（PR）

## 推奨フロー（MVP）
1) 指示（人が動かすのはここだけ）
- LINE → n8n（Webhook）
- n8n → Supabase に job 作成（queued）

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
