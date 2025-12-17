# MEGRIBI / めぐり灯 — 現状ステータス

- Last updated: 2025-12-17
- Branch: main
- Commit: d4538a0

## 現在「動いているもの」
- Frontend（Next.js 16 / App Router）
  - Pages: `/`, `/stores`, `/store/[id]`（`id` は slug。`?store=slug` と併用）
  - 店舗メタ（38店舗）: `frontend/src/app/config/stores.ts`（slug = `ol_` を除いたもの）
  - 夜窓（19:00-05:00）の判定/絞り込み: `frontend/src/app/hooks/useStorePreviewData.ts`（サーバ側に同等ロジックを入れない）
  - 二次会スポット: map-link 方式（`frontend/src/app/config/secondVenueMapLinks.ts` で Google Maps 検索リンク生成）
- Frontend API routes（Next / proxy）
  - `GET /api/range` → backend `/api/range`（クエリ透過）
  - `GET /api/forecast_today` → backend `/api/forecast_today`
  - `GET /api/forecast_next_hour` → backend `/api/forecast_next_hour`
  - `GET /api/second_venues` → backend `/api/second_venues`（補助/将来用）
  - `BACKEND_URL` 未設定時の既定値: `http://localhost:5000`（route.ts 側の default）
- Backend（Flask）
  - Health: `GET /healthz`
  - Data: `GET /api/range?store=&limit=`（Supabase `ts.desc` 取得 → `ts.asc` 返却）
  - Forecast（`ENABLE_FORECAST=1` のときのみ）: `GET /api/forecast_today?store=` / `GET /api/forecast_next_hour?store=`
  - Second venues（補助）: `GET /api/second_venues?store=`（Supabase 未設定/例外でも `{ ok:true, rows: [] }`）
  - Tasks:
    - `GET|POST /tasks/multi_collect`（38店舗収集 → Supabase `public.logs` insert）
    - `GET|POST /api/tasks/collect_all_once`（alias）
    - `GET /tasks/tick`（legacy: 単店舗 + ローカル保存 + 任意で GAS append。Supabase `logs` insert ではない）
- Deploy / 運用（方針）
  - Frontend: Vercel / Backend: Render
  - Production cron assumption: 5分間隔で `GET /tasks/multi_collect`（運用側で 19:00-05:00 を想定）

## 完了済み（P0）
- `/api/range` で `limit=400` 点取得でき、グラフ表示まで一連の確認ができた
- Frontend ルーティング追加: `/stores`, `/store/[id]`
- Lint: ESLint flat config 安定化（`eslint src`、`next lint` は使わない）
- Vercel: Next.js セキュリティブロックを `next@16.0.10` で解消

## いまの課題・違和感
- 体感速度: Next dev 初回コンパイルが 10秒以上かかることがある（遅延=API 不調ではない）
- Lint warnings が残っている（error なし）
- UI の一部がダミー/仮表示
  - `/` の「近くの店 / 今夜のおすすめ / ブログ」
  - `StoreCard` の stats が「pending/準備中」
  - `/stores` の「営業中件数」「おすすめエリア」がダミー表示
- ルート未実装のリンクが存在（例: `/terms`, `/privacy`, `/contact`, `/about`, `/blog`）

## 次にやること（P1候補）
- 体感速度の改善（loading/skeleton、fetch 並列化、キャッシュ方針）
- 404 画像（`/images/blog-*.jpg`）整理
- lint warnings の段階的解消（`any` / unused 等）

## 参照ドキュメント
- INDEX.md
- DECISIONS.md
- API_CONTRACT.md
- ARCHITECTURE.md
- RUNBOOK.md
- CRON.md
- ENV.md
- SECOND_VENUES.md
- ROADMAP.md
- CHECKLISTS.md
- ONBOARDING.md
