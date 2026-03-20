# MEGRIBI / Oriental Lounge Monitor

このリポジトリは、MEGRIBI の混雑可視化を支える Flask API と Next.js 16（App Router）のフロントエンドを含むモノレポです。
運用・制約・設計の正本は plan/ 配下にあります。

## Read First（読む順番）
1. README.md
2. [plan/INDEX.md](plan/INDEX.md)
3. [plan/CODEx_PROMPTS.md](plan/CODEx_PROMPTS.md)
4. [plan/STATUS.md](plan/STATUS.md)
5. [plan/DECISIONS.md](plan/DECISIONS.md)
6. [plan/API_CONTRACT.md](plan/API_CONTRACT.md)
7. [plan/ARCHITECTURE.md](plan/ARCHITECTURE.md)
8. [plan/RUNBOOK.md](plan/RUNBOOK.md)
9. [plan/CRON.md](plan/CRON.md)
10. [plan/ENV.md](plan/ENV.md)
11. [plan/SECOND_VENUES.md](plan/SECOND_VENUES.md)
12. [plan/ROADMAP.md](plan/ROADMAP.md)

## Quick Start（ローカル起動）
Backend（Flask）
```
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
# .env に必要な環境変数を設定（plan/ENV.md 参照）
python app.py
```

Frontend（Next.js）
```
cd frontend
npm install
# frontend/.env.local に必要な環境変数を設定（plan/ENV.md 参照）
npm run dev
```

## 重要な制約（必ず守る）
- `/api/range` の引数は `store` / `limit` のみ（from/to などの追加は禁止）。
- 夜窓（19:00–05:00）の判定・絞り込みはフロント責務。
- データの正本は Supabase `logs`。Google Sheet / GAS はレガシー fallback。
- レイヤ構造は Supabase → Flask → Next.js を維持（フロントから Supabase を直接叩かない）。
- 二次会スポットは map-link 方式（Places API 依存に戻さない）。
- 秘密値はコードに書かない。環境変数のみ（`NEXT_PUBLIC_*` に秘密を入れない）。

## よくある詰まり（PowerShell）
- `[]` を含むパスは `-LiteralPath` を使う（例: `frontend/src/app/insights/weekly/[store]/page.tsx`）。
- `Get-Content -Raw` が使えない環境では `Get-Content ... | Out-String` を使用。
- ドキュメントは UTF-8 (no BOM) + LF を維持。CRLF で差分が出やすい点に注意。

## やらないこと（抜粋）
- `/api/range` にクエリ追加・サーバ側の夜窓フィルタ追加。
- Places API / DB 保存を前提に二次会スポットを作り直す。
- フロントから Supabase に直接アクセス。

詳細は [plan/DECISIONS.md](plan/DECISIONS.md) を参照してください。
