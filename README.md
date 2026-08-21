# MEGRIBI / Oriental Lounge Monitor

このリポジトリは、MEGRIBI の混雑可視化を支える Flask API と Next.js 16（App Router）のフロントエンドを含むモノレポです。
運用・制約・設計の正本は **[`plan/README.md`](plan/README.md)**（ナビ）と `plan/*.md` にあります。

## Read First（読む順番）
1. **[CLAUDE.md](CLAUDE.md)**（3分マップ・**最初に読む**。plan/ 配下より新しく、迷ったらここを優先）
2. README.md（本ファイル）
3. **[plan/README.md](plan/README.md)**（`plan/` の目次・**Cursor/AI はここから**）
4. [plan/INDEX.md](plan/INDEX.md)（主要パス・Constraints のクイック参照）
5. [plan/CODEx_PROMPTS.md](plan/CODEx_PROMPTS.md)
6. [plan/STATUS.md](plan/STATUS.md)（プロジェクト全体の STATUS）
   - **定時ブログ Cron の監視・再実行**はリポジトリ直下 [**STATUS.md**](STATUS.md) を参照
7. [plan/DECISIONS.md](plan/DECISIONS.md)
8. [plan/API_CONTRACT.md](plan/API_CONTRACT.md)
9. [plan/API_CURRENT.md](plan/API_CURRENT.md)（`/api/current` の位置づけ・補足）
10. [plan/ARCHITECTURE.md](plan/ARCHITECTURE.md)
11. [plan/RUNBOOK.md](plan/RUNBOOK.md)（起動・定期ジョブ・オンボーディング）
12. [plan/ENV.md](plan/ENV.md)
13. [plan/SECOND_VENUES.md](plan/SECOND_VENUES.md)
14. [plan/VISION_AND_FUTURE.md](plan/VISION_AND_FUTURE.md)（構想・今後の実装段取り）
15. [plan/ROADMAP.md](plan/ROADMAP.md)
16. [plan/GLOSSARY.md](plan/GLOSSARY.md)（用語）

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

> **API 契約の正本は `CLAUDE.md` §3「絶対不変リスト」**。同じ内容を複数の文書に書くと必ず食い違うため、
> ここには要点だけを置き、詳細は CLAUDE.md を見ること（食い違いを見つけたらコードが正）。

- `/api/range` の必須引数は `store` + `limit`。任意で `from` / `to`（YYYY-MM-DD・**日付粒度のみ**）を受ける。
  **時刻粒度のサーバー側フィルタは禁止**（夜窓の判定はフロントの責務）。
- 夜窓（19:00–05:00）の判定・絞り込みは **店舗 UI** とし、フロント（`useStorePreviewData.ts`）で行う。LINE 下書きは `insightFromRange.ts`（Next サーバー）で、**取得済み `/api/range` に対して**窓計算（Flask 側は日付粒度までしか絞らない）。
- データの正本は Supabase `logs`。Google Sheet / GAS はレガシー fallback。
- レイヤ構造は Supabase → Flask → Next.js を維持（フロントから Supabase を直接叩かない）。
- 二次会スポットは map-link 方式（Places API 依存に戻さない）。
- 秘密値はコードに書かない。環境変数のみ（`NEXT_PUBLIC_*` に秘密を入れない）。

## よくある詰まり（PowerShell）
- `[]` を含むパスは `-LiteralPath` を使う（例: `frontend/src/app/insights/weekly/[store]/page.tsx`）。
- `Get-Content -Raw` が使えない環境では `Get-Content ... | Out-String` を使用。
- ドキュメントは UTF-8 (no BOM) + LF を維持。CRLF で差分が出やすい点に注意。

## やらないこと（抜粋）
- `/api/range` に**時刻粒度**のクエリ追加・サーバ側の夜窓フィルタ追加。
  （`from`/`to` の**日付粒度**は実装済みの正式な契約。詳細は `CLAUDE.md` §3）
- Places API / DB 保存を前提に二次会スポットを作り直す。
- フロントから Supabase に直接アクセス。

詳細は [plan/DECISIONS.md](plan/DECISIONS.md) を参照してください。
