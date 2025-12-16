# MEGRIBI / めぐり灯 — Codex Master Prompts（正式版）

Last updated: 2025-12-16  
commit: TODO

---

## このドキュメントの位置づけ

この `plan/CODEx_PROMPTS.md` は、  
**MEGRIBI（めぐり灯）プロジェクトにおける Codex / ChatGPT 用の唯一の正本（single source of truth）** です。

今後、チャット冒頭に毎回長文の「マスタープロンプト」を貼る必要はありません。  
Codex には **「このファイルを必ず読め」** と指示するだけで十分です。

---

## プロジェクト共通前提

- 対象リポジトリ: `riental-lounge-monitor-main/`
- このチャットでは **本リポジトリの開発のみ** を扱う
- データソースの source of truth は **Supabase `logs` テーブル**
  - Google Sheet / GAS はレガシー fallback
  - 機能拡張は禁止
- フロントエンド
  - Next.js 16（App Router）
  - TypeScript / Tailwind CSS
  - 既存ルーティングを壊さないこと  
    `/`, `/stores`, `/store/[id]`, `src/app/api/*/route.ts`

---

## 重要な設計制約（絶対遵守）

### /api/range の制約
- 受け付けるクエリは **store / limit のみ**
- Supabase では `ts.desc` で取得し、**レスポンスは ts.asc に並べ替える**
- from / to などの時間フィルタを **追加してはいけない**
- 19:00–05:00 の night window 判定は **フロントエンド責務**
  - `useStorePreviewData.ts`
  - バックエンドに同様のロジックを入れない

### 既存 API 互換性
- `/health`
- `/api/meta`
- `/api/current`
- `/api/range`
- `/api/forecast_*`
- `/tasks/tick`

これらの挙動を **壊してはいけない**。

### Second Venues
- map-link 方式が正
- Google Places API による詳細収集は原則行わない
- `/api/second_venues` は補助情報でありコアではない

---

## 機密情報の扱い

- Supabase URL / KEY
- Render 環境変数
- Google API Key

**すべてハードコード禁止**  
必ず環境変数経由で扱うこと。

---

## 出力・作業ルール

### patch(diff) ルール
- 変更は必ず patch(diff) 形式で提示
- 広範囲・破壊的変更は事前説明なしに行わない

### PowerShell ルール
- 実行コマンドは **必ず 1 つのコードブロック**
- `cd` パスは実ディレクトリ構成に正確に合わせる

---

## ネットワーク / DNS 注意事項

以下のエラーが出た場合：

- Temporary failure in name resolution
- getaddrinfo ENOTFOUND

**コードや URL を変更して直そうとしないこと。**

まず：
- ローカル PC の DNS 問題の可能性を説明
- Render 本番環境での再現確認
- Render Logs の確認

を提案すること。

---

## モード判定（必須）

ユーザー入力を以下のいずれかに分類する。

- [ONBOARDING]
- [BUGFIX]
- [FEATURE]
- [REFACTOR]
- [DOC]
- [EXPLAIN]

最初に **判定したモード + 要約 + 関連ファイル名** を提示する。

---

## モード別フロー概要

### [ONBOARDING]
- 現状整理・方針確認のみ
- diff は出さない
- 読むべきファイル・注意点を列挙

### [BUGFIX]
- ログ・テストから原因候補を列挙
- 修正方針 → 最小 diff
- 実行コマンドを最後に提示

### [FEATURE]
- 既存仕様との整合性確認
- 設計メモ → diff
- 必要なテスト・requests.http を提案

### [REFACTOR]
- 目的明示
- API 互換性チェック
- 小さなステップで diff

### [DOC]
- 実装との差分指摘
- Last updated / commit を追記

### [EXPLAIN]
- 読み解きのみ
- diff は出さない

---

## 出力フォーマット（厳守）

1. モード判定 + 要約  
2. 方針・設計  
3. patch(diff)（必要な場合のみ）  
4. 実行コマンド一覧

---

## 補足運用ルール

- ユーザーは短文・ログ断片のみ送ることが多い
- モード未指定時は内容から推測する
- 大規模変更は **設計 → 確認 → diff**

---

以上。
