# VISION_AND_FUTURE
Last updated: 2026-03-29 (Round 8 完了)
Target commit: (see git)

> **このファイルの役割**  
> プロジェクトの**構想・展望・実装の段取り**を、会話や記憶に依存せず `plan/` に固定する。  
> **現状の事実（何が動いているか）**は `plan/STATUS.md` が正。  
> **壊してはいけない契約**は `plan/DECISIONS.md` / `plan/API_CONTRACT.md`。  
> **細かい工程表**は本書＋ `plan/ROADMAP.md` を併読する。

---

## 1. プロジェクトの目的（プロダクト）

- **MEGRIBI（めぐりび）**: 相席ラウンジ等の **混雑の可視化** と **ML ベースの予測** を通じて、来店タイミングの判断材料を提供する Web サービス。
- **データの正本**: Supabase `logs`。収集は **Render Starter**（$7/月、2025-12 移行済み）上の Flask／`multi_collect` 系。スリープなし
- **フロント**: Next.js（Vercel）。コンテンツは 3 分類運用:
  - **Daily/Weekly Report**: 完全自動（GitHub Actions + Gemini + cron-job.org）
  - **Editorial Blog**: AI 下書き＋LINE 承認の半自動運用
- **ML**: XGBoost ベースの店舗別最適化モデル（38 店舗分）。日次自動学習

### 個人のビジョン（参考・plan の必須要件ではない）

- 趣味・個人開発としての側面、収益・自動化・メディア化などの**志向**は、オーナーの判断としてありうる。
- **リポジトリの技術ドキュメント（`plan/*.md`）は主に実装・運用契約**を記す。

---

## 2. 現状の到達点（Round 8 完了 / 2026-03-29）

詳細は **`plan/STATUS.md`**。

| 領域 | 状態 |
|------|------|
| 収集 → Supabase | 本番稼働。cron-job.org → Flask `/tasks/multi_collect`（`CRON_SECRET` 認証）|
| Flask API | `/api/range` `/api/megribi_score` `/api/forecast_*` `/api/forecast_today_multi` `/api/forecast_accuracy` 等 13 エンドポイント稼働 |
| Next.js 画面 | 14 ページルート実装済み（`/` `/stores` `/store/[id]` `/compare` `/reports` `/reports/*/[store_slug]` `/blog` `/mypage` 等）。`/insights/weekly` は `/reports/weekly` に 301 リダイレクト |
| Next.js API | 14 API route 稼働（proxy + cron + LINE + SNS） |
| AI 予測レポート | Daily: 38 店舗 × 2 回/日、Weekly: 38 店舗 × 1 回/週。全自動 |
| Editorial Blog | LINE → Gemini → 承認 → 公開。半自動 |
| ML 予測 | 店舗別 XGBoost モデル（ML 3.0）。Optuna HPO + Early Stopping + Holdout Test 評価。日次自動学習 |
| megribi_score | Flask + Next.js proxy。トップ「今夜のおすすめ」+ マイページカード |
| マイページ | ダッシュボード化完了（リッチカード・スパークライン・ML 予測・レポートリンク） |
| X 自動投稿 | OAuth 1.0a 実装済み。Daily Report 後に自動トリガー。日本語店舗名テンプレート |
| Recharts 統合 | Chart.js 完全削除、全チャート Recharts に統一 |
| パフォーマンス最適化 | ThreadPoolExecutor 並列化 + forecast_today_multi バッチ + request ordering 戦略（sub-3s 初期表示）|
| GA4 アナリティクス | gtag.js + SPA 追跡 + カスタムイベント（store_view, report_read, favorite）。`NEXT_PUBLIC_GA_MEASUREMENT_ID` で制御 |
| 精度メトリクス API | `/api/forecast_accuracy` — 学習時 MAE/RMSE を metadata.json に永続化し API 提供 |
| ステータス日本語化 | StoreCard バッジ: 狙い目/様子見/他店へ |
| CDN キャッシュ | API proxy に `s-maxage` + `stale-while-revalidate` |
| OGP | 全主要ページに設定済み |
| Sitemap | 全店舗の Daily/Weekly レポート URL 登録済み |
| E2E テスト | Playwright スモークテスト（5 テストグループ）+ CI ワークフロー |
| エラー/ローディング UX | 全主要ページに `error.tsx` / `loading.tsx` 配置（11 ファイル） |
| Weekly Insights 統合 | `/reports/weekly` に MDX + 定量データ（チャート・Good Windows・メトリクス）を統合表示 |
| PAT 期限切れ監視 | 週次 GHA + LINE Push で GitHub PAT 有効期限を通知 |
| PWA | Manifest + アイコン PNG + Service Worker。ホーム画面追加・オフラインフォールバック |
| 動的 OG 画像 | 全主要ページに `opengraph-image.tsx` 配置（Edge Runtime 動的生成） |
| 店舗比較ページ | `/compare` — 最大3店舗を並べてマージチャート + リアルタイム比較 |
| LINE Editorial 拡張 | 月間まとめ・エリア比較スコープ対応 |

---

## 3. 方針（既に決まっていること）

- **n8n**: 使わない（廃止・非採用）
- **PR の URL を LINE に自動送信**: 当面やらない
- **二次会スポット**: map-link が本流（`plan/SECOND_VENUES.md`）
- **`avoid_time`**: 「窓内で total が最小の時刻」。読者向けには「入店しやすさの目安」
- **X 自動投稿**: 全店舗一斉ポストは行わない。段階的拡大
- **Daily Report トリガー**: GHA native schedule が正本（`cron: "0 9 * * *"` / `"30 12 * * *"`）。cron-job.org 不要
- **`/reports` 統合**: 1 ページに Daily/Weekly をタブ切替。個別レポートは SEO 用固定 URL

---

## 4. 展望とフェーズ（実装の目安・順番）

### フェーズ A — 運用の安定・既存の磨き込み ✅ 大部分完了

**完了した項目**:
1. ✅ LINE 下書きの品質確認（`RANGE_LIMIT` 調整済み）
2. ✅ Web フロント全ページ実装（トップ・店舗一覧・詳細・レポート・マイページ・ブログ）
3. ✅ `plan/*` と STATUS の同期
4. ✅ CDN キャッシュ・パフォーマンス最適化
5. ✅ Chart.js → Recharts 統合
6. ✅ StoreCard UI 改善

**残タスク**:
- ~~デッドコード削除~~ → ✅ Round 6 完了
- Weekly Insights のパラメータ調整
- `/api/current` の位置づけ決定
- ~~`/insights/weekly` と `/reports/weekly` の重複整理~~ → ✅ Round 6 統合完了（301 リダイレクト + `insight_json` 表示）
- ~~E2E テスト / error.tsx / loading.tsx の充実~~ → ✅ Round 6 完了

### フェーズ B — 発信（X / 拡散）✅ 基盤完了

**完了した項目**:
1. ✅ X (Twitter) API 統合（OAuth 1.0a、`/api/sns/post`）
2. ✅ GHA ワークフロー `x-auto-post.yml`（Daily Report 後自動トリガー）
3. ✅ OGP（`og:title` / `og:image`）設定済み
4. ✅ 許可店舗制御（`SNS_POST_ALLOWED_STORE_SLUGS`）
5. ✅ dry_run / 段階的拡大の仕組み

**残タスク**:
- X API キーの本番設定と dry_run 解除（コード側は準備完了。Vercel/GHA に環境変数設定後、`workflow_dispatch` で dry_run=true テスト → false で解除）
- OG 画像の動的生成（予測サマリ入り）
- アフィリエイト枠の検討（予約リンク + UTM）

### フェーズ C — 予測・ML の「本番品質」 ✅ 大部分完了

**現状の技術的事実**:
- **ML 3.0 本番稼働**: 38 店舗別 XGBoost モデル。Optuna HPO + Early Stopping。日次自動学習
- **特徴量**: 29→19 に最適化（推論時 NaN のラグ系・重複 `dow`・`gender_diff` を除外）
- **評価基盤**: 時系列 Train/Test Split（80/20）。Holdout Test で真の汎化精度を測定
- **Feature Importance**: metadata.json に店舗別で永続化
- **`megribi_score`**: 女性比率・占有率・安定性から算出。トップ・マイページで表示
- **`model_registry.py`**: Supabase Storage からモデルダウンロード・キャッシュ・スキーマ検証（v2）
- **パフォーマンス最適化（Round 4.5 完了）**:
  - `megribi_score` / `range_multi` / `forecast_today_multi`: ThreadPoolExecutor(12) で並列化
  - `forecast_today_multi`: 12 店舗の個別 API 呼び出しを 1 バッチに集約
  - `/stores` ページ: request ordering 戦略で単一 gunicorn worker でも ~1.5s 初期表示
  - `/store/[id]` ページ: range + forecast を Promise.all で同時発火
  - Flask プロセス内キャッシュ（TTL 60s）で forecast 結果を個別/バッチ間共有

**残タスク**:
1. ~~オフライン評価（精度の見える化）~~ → ✅ MAE/RMSE の metadata.json 永続化 + API 完了。**フロントエンド表示は未着手**
2. 異常値・欠損時のユーザー向けメッセージ改善
3. 予測精度の定期レポート（Weekly Report への組み込み等）
4. ヒートマップ画像生成（将来）
5. モデルのプリロード（起動時に全店舗モデルをメモリに載せる — GIL ボトルネック軽減）
6. 精度トレンドの可視化（日次メトリクスの履歴蓄積）

### フェーズ D — PWA・通知 ⚙️ 部分完了

**ゴール**: ホーム画面追加・リピーター向け通知。

1. ✅ Web App Manifest、Service Worker（Round 7 完了）
2. Web Push（VAPID、購読の保存、送信ジョブ）

### フェーズ E — 課金・プレミアム

**ゴール**: Stripe 等による B2C 課金。**当面は優先度低**。

1. Checkout / Webhook / 会員フラグ
2. プレミアム限定機能（リアルタイム通知・高精度予測等）

---

## 5. 「公開までフル自動」への切り替え（将来オプション）

- **技術的には可能**: 環境変数で自動公開 ON/OFF
- **前提**: ガードレール（禁止語・数値レンジ・店舗整合）、Staging 検証
- **現状**: Daily/Weekly は完全自動。Editorial は半自動（LINE 承認）

---

## 6. 技術的に追加検討しがちな項目（チェックリスト）

| 区分 | 例 | 現状 |
|------|-----|------|
| 運用 | ヘルスチェックアラート、ログ集約、Supabase バックアップ | 部分実装（GHA 失敗通知あり） |
| 安全 | レート制限、異常検知 | LINE webhook: Upstash。`/tasks/*`: CRON_SECRET |
| 品質 | 下書きの自動チェック、API テスト | Zod 検証済み。Python テスト 13 ファイル |
| 発信 | X API、OGP、画像生成 | ✅ X API + OGP 完了。画像生成は未着手 |
| 課金 | Stripe、Webhook、権限制御 | 未着手 |
| 法令 | プライバシーポリシー、Cookie 同意 | フッターにリンクあり |

---

## 7. 関連ドキュメント

| ファイル | 内容 |
|----------|------|
| `plan/README.md` | **plan フォルダの目次** |
| `plan/STATUS.md` | **いま動いているもの** |
| `plan/ROADMAP.md` | **P0/P1/P2 と Round 5 以降の提案** |
| `plan/BLOG_PIPELINE.md` | LINE・Gemini・`blog_drafts` |
| `plan/BLOG_CONTENT.md` | ブログ方針・Facts と文章の分離 |
| `plan/DECISIONS.md` | 変更してはいけない判断 |
| `plan/ARCHITECTURE.md` | データフロー |
| `plan/RUNBOOK.md` | 起動・定期ジョブ・オンボーディング |

---

## 8. AI / 開発者向けメモ

- ユーザーが「以前決めた展望は？」と聞いたら **本ファイルと `ROADMAP.md` を先に読む**。
- 実装の真実は **コード**。本書と矛盾したら **コードを確認し、本書または STATUS を更新する**。

---

## 9. 全店展開・SEO・Cron・SNS（スケール方針の記録）

> テストは当面 **指定店舗のみ**でも、設計判断を忘れないため **ここに固定**する。

### 9.1 ブログと SEO（同一 URL の上書き）

- **想定負荷**: 最大 38 店舗 × 1 日 2 本の Daily Report
- **方針**: 店舗・日付ごとに同一 `facts_id` に対応する公開 URL を維持し、上書き更新
- **狙い**: カニバリゼーション回避、情報の鮮度（Freshness）優先

### 9.2 Cron とスケール

- **Daily**: GHA native schedule → matrix 38 店舗（`max-parallel: 15`）
- **Weekly**: GHA schedule → Fan-in Matrix（`max-parallel: 10`）
- **課題**: 店舗数増加時は `max-parallel` 調整。非同期キューは `BLOG_CRON_ASYNC_FUTURE.md`

### 9.3 X（Twitter）自動投稿

- **方針**: 全店舗一斉ポストは行わない（API 制限・シャドウバンリスク）
- **現状**: OAuth 1.0a 実装済み。`x-auto-post.yml` で Daily Report 後に自動トリガー
- **許可店舗**: `SNS_POST_ALLOWED_STORE_SLUGS`（CSV）+ nagasaki。dry_run から段階的に解除
- **将来**: 投稿テンプレートの多様化、Weekly Report の X 投稿追加
