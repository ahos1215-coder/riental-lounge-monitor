# MEGRIBI / Oriental Lounge Monitor

このリポジトリは、MEGRIBI の混雑可視化を支える Flask API と Next.js 16（App Router）のフロントエンドを含むモノレポです。
運用・制約・設計の正本は **[`plan/README.md`](plan/README.md)**（ナビ）と `plan/*.md` にあります。

## Read First（読む順番）
1. README.md（本ファイル）
2. **[plan/README.md](plan/README.md)**（`plan/` の目次・**Cursor/AI はここから**）
3. [plan/INDEX.md](plan/INDEX.md)（主要パス・Constraints のクイック参照）
4. [plan/CODEx_PROMPTS.md](plan/CODEx_PROMPTS.md)
5. [plan/STATUS.md](plan/STATUS.md)（プロジェクト全体の STATUS）
   - **定時ブログ Cron の監視・再実行**はリポジトリ直下 [**STATUS.md**](STATUS.md) を参照
6. [plan/DECISIONS.md](plan/DECISIONS.md)
7. [plan/API_CONTRACT.md](plan/API_CONTRACT.md)
8. [plan/API_CURRENT.md](plan/API_CURRENT.md)（`/api/current` の位置づけ・補足）
9. [plan/ARCHITECTURE.md](plan/ARCHITECTURE.md)
10. [plan/RUNBOOK.md](plan/RUNBOOK.md)（起動・定期ジョブ・オンボーディング）
11. [plan/ENV.md](plan/ENV.md)
12. [plan/SECOND_VENUES.md](plan/SECOND_VENUES.md)
13. [plan/VISION_AND_FUTURE.md](plan/VISION_AND_FUTURE.md)（構想・今後の実装段取り）
14. [plan/ROADMAP.md](plan/ROADMAP.md)
15. [plan/GLOSSARY.md](plan/GLOSSARY.md)（用語）

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
- 夜窓（19:00–05:00）の判定・絞り込みは **店舗 UI** とし、フロント（`useStorePreviewData.ts`）で行う。LINE 下書きは `insightFromRange.ts`（Next サーバー）で、**取得済み `/api/range` に対して**窓計算（Flask `/api/range` の契約は不変）。
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
