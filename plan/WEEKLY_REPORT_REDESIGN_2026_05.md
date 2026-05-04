# WEEKLY REPORT REDESIGN — Weekly Report の存在意義立て直し

Last updated: 2026-05-04
Status: 全 Phase 実装完了 + ユーザーフィードバック反映済 + AI 生成は本番反映待ち (Gemini 無料枠の日次クォータ復帰待ち)

## 目的

Weekly Report が「過去のデータをグラフ化しただけで来週どう動くか分からない」状態になっていた問題を解消する。Daily Report との役割分担を明確化し、Weekly は「先週の振り返り + 来週の戦略」を 1 ページで完結させる。

## 背景 — リデザイン前の問題点 (2026-05-03 時点)

ユーザーから「存在意義が見いだせない」とのフィードバック。プロのプロダクト視点で識別した 7 つの問題:

1. **冒頭文の重複**: リードと本文冒頭でほぼ同じ文 (「毎週水曜に更新される...」) を 2 回表示
2. **メタ情報の羅列で結論なし**: 「993 件 / 49 人 / 信頼度 高」が「で?」になる
3. **時系列折れ線が読み解けない**: 7 日 × 24 時間の折れ線では曜日パターンが見えない
4. **賑わいスコアが 1 件だけ**: ランキングなのに 1 つでは無意味
5. **「賑わいやすい時間帯」がピンポイントの過去日付**: 「4/28 22:25(火)〜」では来週の判断に使えない
6. **AI 解説文が存在しない**: Daily Report と違って自然文の語りがゼロ
7. **来週への示唆がない**: 振り返りだけで Weekly の本来の価値の半分が抜けている

## 設計方針

| Daily Report | Weekly Report (v2) | Editorial |
|---|---|---|
| **点** (今夜の予測・観察) | **線** (1 週間のパターン + 来週の戦略) | **面** (長期トレンド・読み物) |
| 100-200 字自然文 / 店舗 / 日 / 2 版 | 多セクション統合表示 / 店舗 / 週 | 不定期 LINE 経由 |

Weekly Report の中核的価値は **曜日 × 時間帯ヒートマップ**。Daily では絶対に見えない情報。

## 実装プラン (4 Phase + ポリッシュ)

### Phase A: メトリクス解釈強化 ✅ 実装済
**対象**: `scripts/generate_weekly_insights.py` の `_compute_metric_interpretations()`

- [x] `metric_interpretations` フィールドを `insight_json` に追加
- [x] `daily_avg_count` (1日平均件数) + `volume_label` (平常 / やや少なめ / 少ない)
- [x] `baseline_label` (大型店レベル / 中規模店レベル / 小規模店または閑散時間が多め)
- [x] フロント (`/reports/weekly/[store]/page.tsx`) のメトリクスカードに表示

### Phase B: 曜日 × 時間帯ヒートマップ ✅ 実装済 (核心)
**対象**: 新規 `frontend/src/components/WeeklyHeatmap.tsx`

- [x] backend で `_build_day_hour_heatmap()` を実装 — 7 曜日 × 10 時間 (19-04時)
- [x] **0-4 時のデータは前日の夜セッションとして集計** (例: 日曜 00:00 → 土曜行)。理由: 「日曜深夜が混雑」のような直感に反する表示を消すため
- [x] フロント `WeeklyHeatmap.tsx` 新規作成
- [x] **軸**: 時間 (Y) × 曜日 (X)。1 行スキャンで「22 時の週内変動」が読める
- [x] 色: データセット内最大値で正規化 + ガンマ 0.55 + 多色グラデ (青 220° → 紫 290° → 桃赤 345°)
- [x] ホバー時に詳細表示 (混雑度% / 女性比% / サンプル数)
- [x] 旧「1 週間の混雑推移」折れ線グラフを削除

### Phase C: AI 自然文解説 (2 セクション分割) ✅ 実装済
**対象**: `scripts/generate_weekly_insights.py` の `_generate_ai_commentary()`

- [x] 旧 `ai_commentary` 単一文字列 → 新 `last_week_summary` + `next_week_forecast` の 2 フィールドに分割
- [x] Gemini 2.5 Flash + `responseSchema` で構造化出力強制
- [x] **トーン**: です・ます調、砕けた語尾 (〜だね/〜よ/〜みたい) 禁止
- [x] **構造**: リード文 1 行 + Markdown 箇条書き 3-5 項目 (必須)
- [x] フロントは ReactMarkdown + remarkGfm で `<ul><li>` レンダ (SEO 強化)
- [x] **環境変数**: `INSIGHTS_GENERATE_AI_COMMENTARY=1` + `GEMINI_API_KEY` 両方必須
- [x] **耐障害性**:
  - `maxOutputTokens=2000` で出力切断防止
  - `responseSchema` 強制で JSON エスケープを Gemini 側で正しく処理
  - 万一 JSON parse 失敗時は正規表現フォールバック (`r'"key"\s*:\s*"((?:[^"\\]|\\.)*)"'`) で各フィールド単独抽出
  - 429 リトライ 3 回 (5s/15s/45s バックオフ)
  - `gemini-2.5-flash` 失敗時は `gemini-2.5-flash-lite` (別クォータ枠) にフォールバック
  - 全失敗時は既存 Supabase レコードの `last_week_summary` / `next_week_forecast` を読み出して merge → 上書き消失防止

### Phase D: 来週の狙い目時間 TOP 3 ✅ 実装済
**対象**: `scripts/generate_weekly_insights.py` の `_derive_next_week_recommendations()`

- [x] ヒートマップ上位 3 セル (`sample_count >= 2`) を抽出
- [x] `day_label_ja` / `hour_label` (例: "22:00-23:00") / `avg_occupancy` / `avg_female_ratio` を含む
- [x] フロント (`/reports/weekly/[store]/page.tsx`) で緑枠カード 3 列表示

### ポリッシュ: 日別サマリ追加 ✅ 実装済
**対象**: 新規 `frontend/src/components/WeeklySummary.tsx` + backend `_build_daily_summary()`

- [x] 直近 7 夜分の avg/peak occupancy バー一覧
- [x] 各「夜」(19:00-翌04:59) を 1 単位 — ヒートマップと同じ夜セッション基準
- [x] 一番賑わった夜を強調表示
- [x] **ページの最先頭** (タイトル直下) に配置 — 「先週どうだった?」が一番大事だから
- [x] 旧「賑わいスコア」バーチャート (機能重複・直感性ゼロ) を削除

## 最終的なページレイアウト (`/reports/weekly/[store_slug]`)

1. **タイトル + 更新日時** (リード文は短く、重複削除済)
2. **先週の日別サマリ** (`WeeklySummary` — 各夜の avg/peak バー)
3. **先週の傾向** (AI 観測テキスト・紫枠 — `last_week_summary`、ReactMarkdown レンダ)
4. **今週の分析** (メトリクスカード 3 つ + Phase A の解釈ラベル)
5. **曜日 × 時間帯のリズム** (`WeeklyHeatmap` — 軸: 時間×曜日)
6. **来週の予想傾向** (AI 予想テキスト・緑枠 — `next_week_forecast`、ReactMarkdown レンダ)
7. **来週の狙い目時間 TOP 3** (`next_week_recommendations` — 緑枠カード)
8. **賑わいやすい時間帯** (既存 `top_windows` の黄色カード)
9. **予測モデル精度** (`ForecastAccuracyCard`)
10. 公式サイトへのリンク + フッター

## 実装履歴 (コミットログ)

| コミット | 日付 | 内容 |
|---|---|---|
| `b2e43af` | 2026-05-03 | feat: Weekly Report v2 redesign 初版 (Phase A/B/C/D 全部) |
| `eeb4284` | 2026-05-03 | fix: 0-4時の前日扱い + 多色グラデ + 日別サマリ + 賑わいスコアバー削除 |
| `d3e2996` | 2026-05-03 | fix: 軸入れ替え (時間×曜日) + AI 2 セクション分割 + 日別サマリを先頭へ |
| `69296b9` | 2026-05-03 | chore: GHA workflow に `INSIGHTS_GENERATE_AI_COMMENTARY=1` + `GEMINI_API_KEY` 追加 |
| `b4c0751` | 2026-05-03 | fix: JSON parse の堅牢化 (responseSchema + maxOutputTokens=2000 + 正規表現フォールバック) |
| `17a6eab` | 2026-05-04 | fix: トーンを です・ます調に + フロント ReactMarkdown レンダ |
| `f919262` | 2026-05-04 | fix: 箇条書き必須化 (リード文 1 行 + 3-5 項目) |
| `b315919` | 2026-05-04 | fix: 429 リトライ + flash-lite フォールバック + 既存文章保持 |

## 現状の運用ステータス (2026-05-04 時点)

- ✅ 全 Phase 実装完了、テスト pass
- ⚠️ **本番反映は Gemini 日次クォータ次回リセット (UTC 00:00 ≒ JST 09:00) 待ち**
- 過去の手動テスト実行で Gemini クォータを使い切ったため、現在は AI 生成が 429 で失敗する
- フロントは AI フィールドが無くてもヒートマップ・日別サマリ・来週狙い目は正常表示
- 失敗保持機構が動作するため、前回成功した文章 (prose 形式) が表示され続ける店舗もある (今後の cron 実行で箇条書き形式に置き換わる)

## 撤退ライン

- リデザイン後 1 ヶ月、Weekly Report ページの平均滞在時間が 30 秒未満なら廃止して Editorial に統合
- 「曜日 × 時間帯ヒートマップ」の単一画像化 (PNG エクスポート) を SNS 拡散素材として再利用する道も検討余地

## 関連ドキュメント

- `plan/BLOG_REDESIGN_2026_04.md` — Daily Report の Phase 1 改善 (本リデザインは Phase 6 の発展)
- `plan/WEEKLY_INSIGHTS_TUNING.md` — Weekly 生成スクリプトの調整パラメータ
- `plan/DECISIONS.md` #37-43 — Weekly v2 の決定事項
- `plan/STATUS.md` — Weekly Report (v2) セクション
- `plan/ARCHITECTURE.md` — Weekly Report バッチフロー (v2 実装)

## 関連コード

### Backend
- `scripts/generate_weekly_insights.py` — メイン生成スクリプト (v2 ヘルパー全実装)
- `oriental/ml/holiday_calendar.py` — 連休判定 (Phase B/D の「夜セッション」基準と整合)

### Frontend
- `frontend/src/app/reports/weekly/[store_slug]/page.tsx` — ページ本体
- `frontend/src/components/WeeklyHeatmap.tsx` — Phase B
- `frontend/src/components/WeeklySummary.tsx` — ポリッシュ
- `frontend/src/components/WeeklyStoreCharts.tsx` — 旧コンポーネント (実質未使用、`TopWindowChart` 型のみエクスポート)

### Workflow
- `.github/workflows/generate-weekly-insights.yml` — 毎週水曜 06:30 JST、`INSIGHTS_GENERATE_AI_COMMENTARY=1`
