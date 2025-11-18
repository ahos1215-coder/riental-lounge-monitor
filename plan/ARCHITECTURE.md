# ARCHITECTURE.md — システム構成と拡張方針

## 全体像
```
[cron-job.org] --(HTTP)--> [/tasks/tick]         ┐
[cron-job.org] --(HTTP)--> [/health?t=...]       ├--> [Flask / Render] --> [data/*.json / log.jsonl]
[Browser/Next.js Frontend] --(HTTP)--> [API群]   ┘
```

- **Flask**: API 提供。`/api/*` と運用エンドポイント(`/tasks/*`, `/health`)。
- **Render(Starter)**: デプロイ先（Auto-Deploy）。環境変数の注入、ログ監視、ロールバック。
- **cron-job.org**: 5分/30分の定期トリガー。
- **データ**: `data/data.json`（ダミー）, `data/log.jsonl`（JSON Lines）。将来は DB に置き替え。

## 主要コンポーネント
- `oriental/config.py`: 設定読込み（環境変数）。`MAX_RANGE_LIMIT` など。
- `oriental/routes/data.py`: `/api/range` を含むデータ系 API。
- `oriental/routes/tasks.py`: `/tasks/tick` など定期処理。
- `oriental/utils/*`: ロガー・時刻ユーティリティ。

## なぜ「失敗しない API」か
- フロントや集計の連続稼働を優先。境界値はクランプで吸収し、**422 を最小化**。
- 本当に異常なケース（期間逆転など）のみ 422。

## 将来拡張
1. **複数店舗対応**
   - `STORES_JSON`（例: `[{ "id": 38, "name": "長崎店" }, ...]`）でループ収集
   - レスポンスに `store_id` を追加。`/api/meta` で店舗一覧を提供し、`store=` クエリで切替
2. **データストアの導入**
   - Supabase/PostgreSQL か SQLite → Cloud に移行
   - 曜日/時間帯集計テーブルをバッチで前計算
3. **OpenAPI(Swagger)**
   - `openapi.yaml` を生成し、フロントと契約統一
4. **監視/通知**
   - Render Logs に 5xx/タイムアウト監視、失敗時に Slack/LINE 通知
5. **キャッシュ**
   - `/api/range` の期間指定に対し 1〜5分キャッシュでコスト削減

## セキュリティ
- 外部キーは Render の Environment にのみ保存。リポジトリへは `.env.example` のみコミット。
