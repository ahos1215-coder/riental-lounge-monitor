# frontend（めぐりび / MEGRIBI）

Next.js 16（App Router）+ React 19。Vercel に main push で自動デプロイされる。
データは必ず `BACKEND_URL`（Flask）経由で取り、ブラウザから Supabase を直叩きしない。

## ローカル開発（作業ディレクトリの注意）

- **このフォルダ**（`next.config.ts` / `package.json` がある `.../riental-lounge-monitor-main/frontend`）で実行する。
- すでに `frontend` にいる状態で **`cd frontend` をもう一度実行しない**。

```bash
npm run dev          # 開発サーバ（http://localhost:3000）
npm run type-check   # tsc --noEmit
npm run test         # vitest（src/**/*.test.ts）
npm run lint         # eslint src
npm run build        # 本番ビルド
npm run test:e2e     # Playwright（webServer が npm run dev を起動する）
```

## どこを読むか

- `../CLAUDE.md` — リポジトリ全体の3分マップ（**最初に読む**。plan/ と食い違ったらこちらが新しい）
- `../plan/README.md` — 設計判断・契約の深掘り版への案内
- `../plan/ENV.md` — 環境変数（`BACKEND_URL` / `SUPABASE_*` / `NEXT_PUBLIC_SITE_URL` ほか）
- `../docs/LOCAL_LLM_SETUP.md` — Daily / Weekly レポート生成（ローカル Ollama）の正本

## このフォルダの目印

- `src/app/` — App Router のページ（`/`, `/stores`, `/store/[id]`, `/area/[area]`, `/compare`,
  `/reports`, `/reports/daily|weekly/[store_slug]`, `/blog`, `/blog/[slug]`, `/mypage`）
- `src/data/stores.json` — 店舗マスタの正本（Python 側は `oriental/utils/stores.py`。行数は常に一致）
- `src/lib/seo/pageMetadata.ts` — 各ページの title / canonical / OG / Twitter の組み立て
- `src/lib/og/` — OG 画像の共通レイアウト（`opengraph-image.tsx` から呼ぶ）
- `src/proxy.ts` — 存在しない slug を real 404 にするための事前判定（soft-404 対策）
- `vercel.json` — `ignoreCommand` 専用（main 以外のプレビュービルドを止める）。`crons` は置かない。
