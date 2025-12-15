# ONBOARDING
Last updated: YYYY-MM-DD / commit: TODO

「今の MEGRIBI を最初から動かす」ための手順と前提のまとめ。

## 1) Backend (Render Starter, Flask)
- Render Starter で常時起動。`DATA_BACKEND=supabase` をデフォルトに設定。
- 環境変数: `BACKEND_URL`（フロントから参照）、`SUPABASE_URL` / `SUPABASE_ANON_KEY` / `SUPABASE_SERVICE_ROLE_KEY`、`ENABLE_FORECAST`、`STORE_ID`、`MAX_RANGE_LIMIT=50000`。
- デプロイ後、`/tasks/tick` が 5 分間隔で実行され、夜間(19:00–05:00)も連続で 38 店舗を収集。`ENABLE_FORECAST=1` のときのみ予測更新。

## 2) Frontend (Vercel, Next.js 16)
- GitHub 連携 → main への push で自動デプロイ。
- 独自ドメイン `https://meguribi.jp` を割り当て。反映確認時は Shift+F5 / DevTools Network → Disable Cache 推奨。
- `BACKEND_URL` を Render の API に向ける。フロントから直接 Supabase へはアクセスしない。
- `useSearchParams` を使うコンポーネントは必ず `Suspense` 配下に置く。Recharts の Tooltip は `TooltipProps` を独自型で拡張して `label`/`payload` を許容する。

## 3) Local Development
- Backend: `python -m venv .venv && . .venv/Scripts/activate && pip install -r requirements.txt && set DATA_BACKEND=supabase && python app.py`
- Frontend: `cd frontend && npm install && npm run dev`
- 動作確認: `http://localhost:3000/?store=nagasaki` で UI、`http://127.0.0.1:5000/api/range?store=nagasaki&limit=400` で生データ。

## 4) Night Window Responsibility
- 夜時間帯 19:00–05:00 の判定・絞り込みはフロント専任（`useStorePreviewData.ts`）。**バックエンドで時間フィルタを入れない。**

## 5) Second Venues
- 現行仕様は **map-link frontend only**（Google マップ検索リンクを生成するだけ）。Google Places API や Supabase `second_venues` は使用しない。

## 6) Supabase (将来的に使用・強化)
- `logs`/`stores` がシングル source of truth。Render backend は Supabase を読み書きする前提。
- 将来的な拡張: レガシー GAS/Sheet からの完全移行、second venues の軽量レコメンド対応など。環境変数に鍵を置き、ハードコードしない。

