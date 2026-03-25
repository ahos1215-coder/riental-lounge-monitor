# 相談役（Gemini 等）向けブリーフィング
Last updated: 2026-03-25

以下をそのまま（または要約して）外部の AI に貼り付け、**より良い案・優先順位・リスク**についてアドバイスを求める用途向けです。  
リポジトリ内の正本は `plan/*.md` です。

---

## 1. プロジェクト概要

- **名前**: MEGRIBI（めぐりび）/ Oriental Lounge Monitor（リポジトリ名）
- **目的**: 相席ラウンジ等の **混雑状況の可視化** と（設定により）**簡易予測** を通じて、来店タイミングの判断材料を提供する **Web サービス**。
- **開発形態**: **個人開発**（本番運用・収益化の志向はあるが、技術ドキュメント上は必須要件としては書いていない）。
- **データの正本**: **Supabase `logs`**（Google Sheet / GAS はレガシー fallback）。

---

## 2. 技術スタック（現状）

| 層 | 技術 |
|----|------|
| DB / バックエンドデータ | Supabase |
| API | **Flask**（Render 上を想定） |
| フロント | **Next.js 16**（App Router、**Vercel**） |
| 収集 | Python（`multi_collect` 等）、`/tasks/multi_collect` が Supabase へ書き込み |
| バッチ | **GitHub Actions**（週次 Insights、Public Facts → `frontend/content/*` にコミット） |
| LINE 下書き | Vercel の **`POST /api/line`** → Flask `/api/range` 等 → インサイト → **Gemini** → Supabase **`blog_drafts`** |
| 予測 | Flask の `/api/forecast_*`（`ENABLE_FORECAST=1` のとき）。**XGBoost** 系コードは `oriental/ml/` にあり |

---

## 3. 現状（何ができているか）

- **Web**: トップ、店舗一覧・店舗詳細、ブログ、週次インサイト、マイページなど **画面は既に存在**（「これからフロントを一から」ではない）。
- **API**: `/api/range` は公開契約として **`store` と `limit` のみ**（日付でサーバが切らない）。夜の時間帯の絞り込みは **フロント**または **LINE 用インサイト（Next サーバー側）**。
- **LINE**: **n8n は使わない**。Webhook は Next のみ。
- **ブログ**: AI は **下書き〜`blog_drafts` まで**。サイト上の **公開 MDX は半自動（人の確認・PR 前提）**。「公開までフル自動」ではない。
- **週次・Facts**: GitHub Actions で JSON 生成。
- **予測**: 本番 API は有効化フラグ付き。ML の「商品化レベル（ヒートマップ画像パイプライン等）」は **未着手寄り**。

---

## 4. 不変の方針・制約（壊しにくいもの）

- `/api/range` に **from/to 等のクエリ追加やサーバ側夜窓フィルタ**を入れない（契約固定）。
- フロントから **Supabase を直接叩かない**（秘密・レイヤ分離）。
- 二次会スポットは **map-link（検索リンク）** が本流（Places API 前提に戻さない）。
- ブログ／LINE 配管に **n8n は使わない**。
- **PR の URL を LINE に自動送信**は **当面やらない**。

---

## 5. 今後の方針（ドキュメント上のフェーズ）

**優先の目安**（詳細は `plan/VISION_AND_FUTURE.md`）:

- **フェーズ A（今〜短期）**: 運用安定、LINE 下書きの品質、`RANGE_LIMIT` 調整、**既存 UI の改善・コンテンツ拡充**、ドキュメント同期、Weekly Insights の調整、`/api/current` の位置づけ検討。
- **フェーズ B（構想・一部未実装）**: **X（Twitter）** での発信、**投稿用 API ルート**、画像はまずテンプレ／チャート画像から、アフィリエイトは枠と計測から。**OGP / 主要ページのメタデータ**は **実装済み**（`plan/STATUS.md`）。
- **フェーズ C**: 予測の信頼性（オフライン評価、オンザフライ学習 vs 定期学習モデル配布の判断）。
- **フェーズ D**: PWA・Web Push（重いので後段でも可）。
- **フェーズ E**: Stripe 等の課金・プレミアム（構想レベル）。

**将来オプション**: 運用が固まったら **公開までの自動化を ON/OFF**（環境変数等）は技術的には可能だが、**ガードレール・Staging 前提**。未実装。

---

## 6. 相談したいこと（例）

- 個人開発のリソースで、**フェーズ A〜E の優先順位をどう並べるか**。
- **X 集客**と **LINE 下書き**と **SEO/ブログ**のバランス。
- **API 契約を狭く保つ**方針と、プロダクト要望（期間指定など）の両立の仕方。
- **予測・ML**を「売れる品質」にするまでの現実的なマイルストーン。
- 監視・レート制限・バックアップなど **運用の最低ライン**。
- その他、**見落としているリスク**や **もっと軽い実装順**があれば知りたい。

---

## 7. Gemini に一緒にアップロードするとよいファイル（最大 10 個の提案）

リポジトリ内のパス（優先度順）:

1. **`plan/README.md`** — `plan/` の全体マップ  
2. **`plan/STATUS.md`** — 現状の機能一覧（事実）  
3. **`plan/VISION_AND_FUTURE.md`** — 構想・フェーズ・備忘  
4. **`plan/ROADMAP.md`** — P0/P1・当面やらないこと  
5. **`plan/DECISIONS.md`** — 変更してはいけない判断  
6. **`plan/ARCHITECTURE.md`** — データフロー  
7. **`plan/BLOG_PIPELINE.md`** — LINE → Gemini → `blog_drafts`  
8. **`README.md`**（リポジトリ直下）— 制約の短い要約  
9. **`plan/API_CONTRACT.md`** — API 表面積  
10. **`plan/BLOG_CONTENT.md`** — ブログ・Facts の編集方針（半自動の意味）

**代替**: 用語のブレを避けたい場合は **`plan/GLOSSARY.md`** を **10 番目の代わり**に。運用コマンドまで見せたい場合は **`plan/RUNBOOK.md`** を BLOG_CONTENT の代わりに。

---

*このファイルは `plan/BRIEFING_FOR_ADVISOR.md` として保存してある。更新時は日付と内容を合わせること。*

---

## 8. 相談後の整理（Gemini 回答の要約）

返ってきたアドバイスは **`plan/ADVISORY_SYNTHESIS.md`** に構造化して記録する（ROADMAP 等と整合）。
