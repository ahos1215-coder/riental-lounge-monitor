# Gemini レビュー用プロンプト

Last updated: 2026-03-28 (Round 4.5 完了後の包括レビュー)

> このファイルは Gemini（または他の LLM）にプロジェクトの評価レビューと改善提案を求めるためのプロンプトです。
> 以下の「プロンプト本文」セクションをそのままコピーして Gemini に貼り付けてください。
> 可能であれば `plan/STATUS.md`、`plan/ARCHITECTURE.md`、`plan/ROADMAP.md` も添付すると精度が上がります。

---

## プロンプト本文

```
あなたはシニアプロダクトマネージャー兼テックリードとして、以下の個人開発プロジェクトを評価・レビューしてください。忖度なしで、率直な意見と改善案をお願いします。

---

## プロジェクト概要: MEGRIBI（めぐりび）

**ドメイン**: 相席ラウンジ（Oriental Lounge）の混雑可視化 + ML 予測 Web サービス
**URL**: https://www.meguribi.jp
**開発者**: 個人（1人）
**運用期間**: 2025年〜（約1年）
**月額コスト**: Render Starter $7 + Supabase Free + Vercel Free（計 ~$7/月）

### 技術スタック

| レイヤー | 技術 | ホスティング |
|----------|------|-------------|
| データ収集 | Python (BeautifulSoup) + cron-job.org（5分毎） | Render Starter |
| DB | Supabase (PostgreSQL) — logs / blog_drafts / secondary_venues | Supabase Free |
| Backend API | Flask + Gunicorn (2 workers × 2 threads, timeout 300s) | Render Starter ($7/月, 2025-12〜) |
| ML | XGBoost（38店舗別モデル、39特徴量、日次自動再学習） | GHA → Supabase Storage |
| Frontend | Next.js 16 + React 19 + Recharts + Tailwind (ダークテーマ) | Vercel Free |
| コンテンツ生成 | Gemini 2.5 Flash（Daily 76本/日 + Weekly 38本/週） | GHA + Vercel Serverless |
| SNS | X (Twitter) OAuth 1.0a 自動投稿 | GHA workflow_run |
| LINE | Webhook + Gemini → Editorial Blog 半自動公開 | Vercel Serverless |
| CI/CD | 10 GHA ワークフロー（生成・学習・投稿・通知・CI・PAT監視） | GitHub Actions |

### 規模の詳細

**データ収集**:
- 38店舗（日本全国 37 + ソウル 1）を 5分毎にスクレイピング → Supabase logs
- 天気データ統合（Open-Meteo API、都道府県単位でキャッシュ）
- ThreadPoolExecutor(10) で並列スクレイプ（38店舗 ~3-5s）

**ML パイプライン**:
- 39特徴量: 時間帯・曜日・祝日・給料日サイクル・天気・降水・ラグ(12h/24h)・移動平均(2/4step)・sin/cos 時刻エンコード
- 店舗別 XGBoost モデル（men / women 2モデル × 38店舗 = 76モデル）
- 日次自動学習（GHA train-ml-model.yml、180日分データ、週末・雨天に重み 1.8x）
- Supabase Storage にアップロード → Flask ModelRegistry がダウンロード・キャッシュ（TTL 15分）
- megribi_score: 女性比率 × 占有率（理想 70% のベルカーブ）× 安定性 → 0-1 スコア → GO/WAIT/SKIP

**コンテンツ自動生成**:
- Daily Report: 38店舗 × 2回/日（18:00 evening_preview / 21:30 late_update）= 76本/日
- Weekly Report: 38店舗 × 1回/週（水曜 06:30 JST）、Fan-in Matrix 構成
- Editorial Blog: LINE で分析指示 → Gemini 下書き → LINE で「公開」承認 → /blog/[slug]
- X 自動投稿: Daily Report 生成後 workflow_run でトリガー（現在 dry_run）

**フロントエンド**:
- 13 ページルート（トップ・店舗一覧・店舗詳細・レポート統合・Daily/Weekly 個別・ブログ・マイページ・Weekly Insights）
- 13 Next.js API Routes（Flask proxy 7本 + LINE + SNS + cron + reports）
- PWA manifest あり（Service Worker なし）
- OG 画像動的生成（next/og Edge Runtime）
- CDN Cache-Control: s-maxage + stale-while-revalidate

**パフォーマンス最適化（Round 4.5）**:
1. ThreadPoolExecutor(12) で megribi_score / range_multi / forecast_today_multi を並列化
2. forecast_today_multi バッチエンドポイント新設（12店舗の個別呼び出し → 1リクエスト、10s → ~2s）
3. Request Ordering 戦略: range_multi を最優先 await → 部分カード即表示 → megribi → forecast を後続発火
4. Flask プロセス内キャッシュ（forecast TTL 60s）を個別/バッチ間で共有
5. /store/[id] で range + forecast を Promise.all 同時発火
6. 結果: 店舗一覧ページ 体感 ~1.5s で初期表示（progressive rendering）

**セキュリティ**:
- CRON_SECRET Bearer 認証（/tasks/* エンドポイント）
- LINE HMAC-SHA256 署名検証
- Upstash Redis レート制限（LINE webhook: 200 req/min グローバル、20 req/hr ユーザー）
- crypto.timingSafeEqual でタイミング攻撃対策
- SNS_POST_SECRET で X 投稿認証

**テスト**: 27テスト / 16ファイル（25 pass, 1 fail — forecast fallback ロジック）

### 現在の課題（Claude Opus 4.6 による分析）

**最重要**:
- **計測の不在**: GA / Mixpanel 等なし。PV・直帰率・滞在時間・ユーザー行動が完全にブラックボックス
- **X 投稿が dry_run のまま**: コンテンツは毎日 76本生成されているが、実際の配信チャネルが機能していない

**重要**:
- テストカバレッジが薄い（forecast endpoint のテストなし、E2E テストなし）
- Service Worker 未実装（PWA は installable だがオフラインキャッシュなし）
- 予測精度の可視化なし（MAE/MAPE の定期レポートがない）
- ユーザー認証なし（localStorage のみ、お気に入りがデバイス間同期不可）

**中程度**:
- デッドコード 18+ ファイル残存
- Forecast cache が per-worker（Redis 等の共有キャッシュなし）
- 構造化データ（JSON-LD）未実装
- ライトモードなし（ダーク固定）
- /insights/weekly と /reports/weekly の機能重複

### Claude Opus が提案したロードマップ

**Round 5（品質基盤）**: GA 4 導入、デッドコード削除、テスト拡充、構造化データ（JSON-LD）
**Round 6（集客活性化）**: X dry_run 解除 + テンプレート改善、OG 画像に予測データ埋め込み、Service Worker、LINE LIFF
**Round 7（エンゲージメント深化）**: Web Push 通知、店舗比較モード、予測精度ダッシュボード、Supabase Auth
**Round 8（収益化）**: アフィリエイト最適化、Stripe プレミアムプラン、他ブランド対応（JIS・相席屋）

---

## 質問（以下すべてに回答してください）

### 1. プロダクト戦略の評価
- このプロジェクトの **プロダクトとしての強み** と **構造的な弱み** は何ですか？
- 「相席ラウンジの混雑予測」というニッチに **市場性** はありますか？ターゲットユーザーの規模感は？
- 個人開発として **持続可能** ですか？運用コスト・メンテナンス負荷の観点で
- 「データを持っていること」は堀（moat）になりますか？

### 2. 技術アーキテクチャの評価
- Flask + Next.js + Supabase の構成に **技術的リスク** や **改善余地** はありますか？
- 月額 $7 でこの規模のサービスを運用する構成として適切ですか？スケール時のボトルネックは？
- ML パイプライン（XGBoost 38店舗 × 76モデル × 日次再学習 × 39特徴量）の設計は妥当ですか？もっと良い方法はありますか？
- ThreadPoolExecutor 並列化 + Request Ordering 戦略の評価。async (Uvicorn) への移行は必要ですか？
- Gunicorn 2 workers × 2 threads は適切ですか？チューニングの余地は？

### 3. ロードマップへの意見
- Claude Opus の提案した Round 5-8 の **優先順位** は適切ですか？変えるべき点は？
- **抜けている重要な施策** はありますか？
- 個人開発者として、**どこに集中すべき** ですか？（全部やる時間はない前提で）
- Round 5-8 の中で **やらなくていいもの** はありますか？

### 4. 差別化と競合
- 類似サービス（Google Maps の混雑度、食べログ、ぐるなび、相席屋公式アプリ等）と比較して、MEGRIBI の **差別化ポイント** は何ですか？
- この差別化は **守れる** ものですか？（技術的堀、データの堀、ネットワーク効果 etc.）
- **ピボット** すべき可能性はありますか？（相席ラウンジ以外の業態、B2B 向け、API as a Service etc.）

### 5. UI/UX の改善案
- ダークテーマ固定の UX について意見をください
- 「megribi_score → GO/WAIT/SKIP」の表現は直感的ですか？改善案は？
- マイページ（localStorage ベース、ログインなし）の設計は妥当ですか？
- モバイルファーストの観点で改善すべき点は？
- 「38店舗 × 12件/ページ」のページネーションは最適ですか？もっと良い見せ方は？

### 6. 収益化の現実性
- $7/月の運用コストに対して、アフィリエイト収益でペイできる見込みはありますか？
- プレミアムプラン（Stripe 課金）に **課金してもらえる機能** は何ですか？
- 広告モデル vs サブスクモデル vs アフィリエイトモデル、どれが最適ですか？
- B2B（店舗オーナー向けダッシュボード提供）の可能性は？
- Oriental Lounge 公式との **パートナーシップ** の可能性は？（API 提供、データ共有 etc.）

### 7. Claude Opus の分析への反論・補足
- 上記の分析で **見落としている点** や **過大/過小評価** している点はありますか？
- 「計測（GA 4）が最重要」という優先順位に同意しますか？別の見方はありますか？
- 他に **根本的に方向性を変えるべき** 提案はありますか？
- Claude Opus のロードマップに対する **具体的な代替案** があれば提示してください

### 8. ポートフォリオとしての評価
- このプロジェクトを **エンジニアの転職ポートフォリオ** として見た場合、どう評価しますか？
- 技術力のアピールとして **特に強い点** と **補強すべき点** は？
- 「フルスタック × ML × 自動化」の組み合わせは市場でどう評価されますか？
- 面接で聞かれそうな質問と、その回答の方向性を 3 つ挙げてください

### 9. 具体的な次のアクション提案
- 上記すべてを踏まえ、**今後 2 週間で最もインパクトのある 3 つのアクション** を提案してください
- それぞれについて、期待される効果と必要な工数の見積もりもお願いします
- 「やらないこと」リストも提案してください（時間の無駄になりそうな施策）

---

回答は日本語で、各セクションごとに明確に構造化してください。具体的な数字や事例を交えてください。「いい感じですね」のような曖昧な評価ではなく、プロとしての率直な意見をお願いします。必要であれば厳しい指摘も歓迎します。
```

---

## 添付推奨ファイル（精度を上げたい場合）

| # | ファイル | 目的 |
|---|----------|------|
| 1 | `plan/STATUS.md` | 現在動いている機能の完全リスト |
| 2 | `plan/ARCHITECTURE.md` | データフロー・並列化パターン・デプロイ構成 |
| 3 | `plan/ROADMAP.md` | 実装済み Round 1-4.5 + 提案 Round 5-8 |
| 4 | `plan/VISION_AND_FUTURE.md` | プロダクトビジョン・フェーズ計画 |
| 5 | `plan/API_CONTRACT.md` | 全 API エンドポイント契約 |
