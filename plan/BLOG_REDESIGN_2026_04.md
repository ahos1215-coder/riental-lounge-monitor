# BLOG REDESIGN — Daily/Weekly/Editorial 品質改善計画

Last updated: 2026-05-04 (Phase 1 実装済 + Phase 5 を方針変更で置換 + Phase 4/2/3/6 未着手)
Status:
- ✅ **Phase 1 (プロンプト刷新)** 実装済 (`826a97e`, 2026-04-19)
- ✅ **指示文漏洩修正** 実装済 (`fd9a195`, 2026-04-23) — 当初の Phase に無かったが最重要バグとして対応
- ⚠️ **Phase 5 (店舗ページに Daily カード埋め込み)** 方針変更 — 「重複削除のため Daily カードを削除」(`fd9a195`, 2026-04-23) に置換。`/store/[id]` には「今日の傾向まとめ」(LatestForecastSummaryCard) と Weekly Report カードが残置
- ❌ **Phase 4 (フォールバック改善)** 未着手 — 429 等で `buildFallbackBlogDraftMdx()` が発動した際、依然旧スタイル (## 今日の結論 + 箇条書き) で生成される。Phase 1 の自然文と整合しない
- ❌ **Phase 2 (`narrative_hint` ルールベース計算)** 未着手 — Daily Report 用の単調さ解消はまだプロンプト改善のみ
- ✅ **Phase 3 (cron 時間分散)** 実質完了 — `989637e` (2026-04) で `max-parallel: 15 → 5` 削減済。同時 5 並列なら Gemini 無料枠 RPM (~10-15) 内に収まる。当初想定していた「18:00 → 18:00-19:00 に分散」の代わりに、最大同時数を絞ることで 429 を抑制する方針
- ❌ **Phase 6 (Weekly プロンプト刷新)** → 別計画書 `plan/WEEKLY_REPORT_REDESIGN_2026_05.md` に分離して実装済 (2026-05-03〜)

## 目的

Daily Report / Weekly Report / Editorial Blog の自動生成物を、「読みやすい・わかりやすい・AI 臭くない」ものに改善する。特に **各店舗のその日の傾向・特徴が一目でわかる** ことを優先する。

## 背景 (2026-04-19 時点の現状分析)

### 生成パイプライン
| 種類 | 頻度 | 本数/日 or /週 | 経路 |
|---|---|---|---|
| Daily Report | 毎日 18:00 & 21:30 (2版) | 76 本/日 | GHA → `/api/cron/blog-draft` → Gemini 2.5 Flash → Supabase |
| Weekly Report | 毎週水 06:30 | 38 本/週 | `generate_weekly_insights.py` → Gemini → Supabase |
| Editorial Blog | LINE 指示時 | 不定期 | LINE Webhook → Gemini → 下書き → LINE 承認で公開 |

### 5 つの弱点
1. **テンプレ単調**: 箇条書き 3 行 (混雑度 + ピーク時間 + 補足) に固定。量産感が AI 臭さを増幅
2. **指示過多**: 禁止事項羅列 (avoid_time 書くな、数値最小限、挨拶禁止) が「規則遵守ロボット」感を生む
3. **入力データ貧弱**: peak_time / crowd_label / secondary_wave のみ実質活用。男女比・天気・曜日比較などは手元にあるが未連携
4. **Edition 差が浅い**: 18時版と21:30版の差が「見通し vs 実況」の二分のみ
5. **フォールバック露呈**: 429 エラー時の `buildFallbackBlogDraftMdx()` 定型出力が AI 臭い。18:00 cron での瞬間集中が 15 RPM 制限を突破して頻発

## 他 AI 相談の結論と採否

3 AI (Gemini / Claude / ChatGPT) に相談した結果、全員が「Daily 全文生成は廃止、Weekly/Editorial に注力」で一致。ただし **この結論は SEO/PV 最優先の前提に基づく**。本プロジェクトの優先事項「店舗別の毎日の傾向を見せる」とは軸がズレるため、**廃止ではなく改善** で進める。

### 採用する要素
| 要素 | 由来 | 理由 |
|---|---|---|
| ペルソナ + 型プロンプト (禁止羅列→行動指示) | 3 AI 共通 | AI 臭さ除去の最大効果 |
| Few-shot (良い例/悪い例) 埋め込み | 3 AI 共通 | 出力安定 |
| narrative_hint サーバ側事前計算 | Claude | 単調さの根本解消 (AI にフリーハンドを与えない) |
| フォールバック「休止宣言」方式 | Claude | 定型より潔い |
| 時間分散 cron | 本計画独自 | 429 エラー対策 |
| 男女比・天気・曜日比較データ追加 | 共通 | 入力情報量 3 倍化 |

### 不採用の要素
| 要素 | 由来 | 不採用理由 |
|---|---|---|
| Daily 全廃止 | Gemini/Claude/ChatGPT | 店舗別の毎日の傾向表示が目的と相反 |
| earlier_prediction 参照 (21:30 が 18:00 を参照) | Claude | 予測が外れた場合に精度の悪さが露呈するリスク |
| エリア単位集約 | Gemini/Claude | 店舗別傾向の粒度が失われる |

## 設計方針

### トーン
夜遊びに詳しい友人がデータを見ながらつぶやくような温度。断定と過剰演出を避け、「〜そう」「〜らしい」「〜の気配」の観測者の距離を保つ。

### 構造
- 箇条書き禁止、自然文で
- 毎回違う入り方 (narrative_hint により焦点がゆらぐ)
- 100〜200 字程度、無理に延ばさない
- MDX frontmatter から開始、挨拶不要

### 2 版の独立
- **18:00 evening_preview**: 「今夜はこうなりそう」(予測 + コンテキスト)
- **21:30 late_update**: 「今、こうなっている」(現況観察のみ、予測への言及なし)
- **重要**: 2 版は相互参照しない。予測精度のアラ探し動線を作らない
- 予測は断定を避ける (「21時にピークが来ます」❌ → 「21時あたりが山になりそう」✅)

### narrative_hint (サーバ側事前計算)
AI に「何が面白いか」を判断させると外すので、ルールベースで焦点を決める:
- 先週比 ±10% 以上 → `vs_last_same_dow` を焦点に
- secondary_wave.detected が先週なし → `secondary_wave` を焦点に
- extreme_weather フラグあり → `weather` を焦点に
- 男女比が通常から大きく偏る → `gender_ratio` を焦点に
- どれも該当なしなら → `peak_time` を普通に焦点に

## 実装プラン

### Phase 1: プロンプト刷新 (工数 1-2 日) ✅ 実装済 (`826a97e`, 2026-04-19)
**対象**: `frontend/src/lib/blog/draftGenerator.ts`

- [x] System Prompt を「禁止羅列」から「ペルソナ + 行動指示 + 型」へ書き換え
- [x] Few-shot 2 件 (良い例/悪い例) を末尾に固定埋め込み
- [x] 箇条書き禁止を明示、自然文指示を追加
- [x] Edition 別トーン指示を詳細化 (evening_preview = 未来形・推量、late_update = 現在形・観察)
- [x] 禁止事項は最小限に残す (キャバクラ用語、avoid_time のみ)
- [x] **追加対応**: `secondary_wave.note` / `gender_note` から AI 指示語を除去 (`fd9a195`, 2026-04-23)
- [x] **追加対応**: `/store/[id]` の Daily Report カードを削除 (今日の傾向まとめと内容重複) (`fd9a195`, 2026-04-23)

### Phase 2: 入力データ拡張 (工数 2-3 日)
**対象**: `frontend/src/lib/blog/insightFromRange.ts` などのファクト構築層

- [ ] insight_json に以下を追加:
  - [ ] `gender_ratio_recent` (既存 range データから算出)
  - [ ] `weather` (extreme_weather, is_holiday フラグ)
  - [ ] `vs_last_same_dow` (既存 `week_comparison` を構造化)
  - [ ] `location_trait` (店舗のエリア特性。stores.json に項目追加)
- [ ] `narrative_hint` フィールドを追加、ルールベース計算ロジックを実装

### Phase 3: cron 時間分散 (工数 半日)
**対象**: `.github/workflows/trigger-blog-cron.yml` など

- [ ] 18:00 一斉投入 → 18:00-19:00 の 60 分で 38 本を分散 (約 1.6 分/本)
- [ ] 21:30 一斉投入 → 21:30-22:30 の 60 分で分散
- [ ] 429 エラー発生率が下がるか 1 週間モニタリング
- [ ] フォールバック発動回数をログで追跡

### Phase 4: フォールバック改善 (工数 半日)
**対象**: `buildFallbackBlogDraftMdx()` in `draftGenerator.ts`

- [ ] 定型文を廃止、「観測データのみ + コメント休止宣言」に変更
- [ ] 「※今夜はコメント生成を休止しています」の明示
- [ ] frontmatter に `fallback: true` フラグを追加

### Phase 5: 店舗ページへの Daily カード埋め込み (工数 1 日) ⚠️ 方針変更で置換済
**対象**: `frontend/src/app/store/[id]/page.tsx`

- [x] **方針変更**: 「今日の傾向まとめ」(`LatestForecastSummaryCard`) が既に存在し、Daily Report の MDX bullets を抜粋表示している。新規 Daily カード追加ではなく、**重複していた「Daily Report 専用カード」を削除** (`fd9a195`, 2026-04-23)
- [x] 結果: `/store/[id]` には「今日の傾向まとめ」+ Weekly Report 要約カードが残る
- [x] 「詳しく見る」リンクは「今日の傾向まとめ」内に存在 → `/reports/daily/[store_slug]`

### Phase 6: Weekly 強化 (工数 2 日、Phase 1-5 完了後) → 別計画書に分離して大幅実装済
**対象**: `scripts/generate_weekly_insights.py`

当初の「Weekly プロンプト刷新」よりも大規模な改善として、別計画書 `plan/WEEKLY_REPORT_REDESIGN_2026_05.md` に分離して実装した:

- [x] 曜日 × 時間帯ヒートマップ (Phase B)
- [x] AI 自然文解説の 2 セクション化 (Phase C: last_week_summary + next_week_forecast)
- [x] 来週の狙い目 TOP 3 (Phase D)
- [x] メトリクス解釈ラベル (Phase A)
- [x] 日別サマリ追加 + 賑わいスコアバー削除 + 軸入れ替え + 0-4時の前日扱い

詳細は `plan/WEEKLY_REPORT_REDESIGN_2026_05.md` を参照。

## 撤退ライン

- **Phase 1 完了後**: エリア違いの店舗 3-5 本を読み比べて「まだ AI 臭が残る」と感じたら Phase 2 前にプロンプト再設計
- **Phase 3 完了 1 週間後**: フォールバック発動率が 10% を超えていれば有料枠切替を検討
- **全 Phase 完了 1 ヶ月後**: GA4 で Daily Report の平均滞在時間が 15 秒未満なら、Daily は縮小して Weekly/Editorial 全振りへピボット

## 関連ファイル

### 主要コード
- `frontend/src/lib/blog/draftGenerator.ts` — Gemini プロンプト + フォールバック
- `frontend/src/lib/blog/runBlogDraftPipeline.ts` — パイプライン統合
- `frontend/src/lib/blog/insightFromRange.ts` — insight_json 構築
- `frontend/src/app/api/cron/blog-draft/route.ts` — cron 入口
- `scripts/generate_weekly_insights.py` — Weekly 分析
- `.github/workflows/trigger-blog-cron.yml` — Daily cron
- `frontend/src/app/store/[id]/page.tsx` — 店舗詳細ページ (Phase 5)

### 関連ドキュメント
- `plan/BLOG_PIPELINE.md` — 既存パイプライン設計
- `plan/BLOG_CRON_GHA.md` — GHA cron 設計
- `plan/BLOG_CONTENT.md` — コンテンツ方針
