# CODEx_PROMPTS
Last updated: 2025-12-17

MEGRIBI の開発補助 AI（Codex）向けのガイドライン。既存の決定事項と契約を壊さないこと。

---

## Start Here（初見のChatGPT / Codex向け）
このリポジトリはファイル数が多いため、初見のAIは探索で迷子になりがちです。
まず以下の順で読むことで、無駄な探索時間を最小化できます。

1) plan/INDEX.md（全体の地図・読む順番・重要ファイル一覧）
2) plan/STATUS.md（現状の稼働状況 / 今動いている機能）
3) plan/DECISIONS.md（重要な意思決定の履歴）
4) plan/API_CONTRACT.md（API契約。壊してはいけないもの）
5) plan/ARCHITECTURE.md（全体アーキテクチャ）
6) plan/RUNBOOK.md（起動/検証手順）
7) plan/CRON.md / plan/ENV.md（運用と環境変数）
8) plan/SECOND_VENUES.md（二次会スポット方針）

補助：plan/repo_map.txt がある場合は、先に見て全体像を掴む。

---

## 正本（source of truth）の扱い
- 実装の事実（いま実際にどう動いているか）はコードが正
- 設計意図・制約・壊してはいけない前提は plan/*.md が正
- コードと plan が食い違っていた場合は、まず「plan が古い可能性」を前提に差分を確認し、
  基本は plan を更新して整合させる（必要なら、そのうえでコード修正）

---

## Core Principles
- 対象リポジトリ: riental-lounge-monitor-main/ の開発のみを扱う。
- Source of truth: Supabase logs。Google Sheet / GAS は legacy fallback（拡張禁止）。
- Architecture: Supabase -> Flask API（Render）-> Next.js 16（Vercel）。
- Secrets（Supabase URL/KEY, Render/Vercel env, Google API Key など）はコードに書かない。必ず環境変数経由。
  - NEXT_PUBLIC_* に秘密値を入れない（ブラウザへ配布される）。
- 既存 API / ルーティングの互換性を壊さない（特に /healthz, /api/meta, /api/current, /api/range, /api/forecast_*, /tasks/*）。

---

## Frontend Rules（Next.js 16 / App Router）
- 既存ルーティング構成を壊さない:
  - /, /stores, /store/[id], src/app/api/*/route.ts
- /store/[id] は params.id を slug として受け取り、クエリ ?store=slug と併用する前提を変えない。
- Night window（19:00-05:00）の判定・絞り込みはフロント専任（frontend/src/app/hooks/useStorePreviewData.ts）。
  - Backend / Next API routes に同様の時間ロジックを入れない。
- Next.js 16 の制約:
  - useSearchParams / useRouter を使うコンポーネントは Suspense 配下に置く。
- Recharts の型:
  - TooltipProps の label / payload が型定義されていないケースがあるため、独自型で拡張して使う。

---

## Backend Rules（Flask）
### /api/range（最重要制約）
- 公開契約として受け付けるクエリは store + limit のみ（新規クエリ追加禁止）。
- Supabase には ts.desc でクエリし、応答では ts.asc に並べ替えて返す。
- from/to のような時間フィルタや、夜窓（19:00-05:00）のサーバーサイド絞り込みを追加しない。
  - 夜窓ロジックはフロント責務。
- MAX_RANGE_LIMIT（既定 50000）で limit を clamp する。フロント推奨は 200-400。

### Forecast
- /api/forecast_today / /api/forecast_next_hour は ENABLE_FORECAST=1 のときのみ有効。
  - 無効時は 503 { ok:false, error:"forecast-disabled" }。

### Tasks / Cron
- 本番の収集入口は GET /tasks/multi_collect（alias: GET /api/tasks/collect_all_once）。
- /tasks/tick は legacy（単店舗 + ローカル/GAS向け）。Supabase logs insert 経路ではない。

---

## Second Venues（仕様固定）
- 本流は map-link 方式（フロントで Google Maps 検索リンクを生成）。
- Places API によるデータ収集・保存を必須にしない（その設計に戻さない）。
- Backend の /api/second_venues は補助/将来用として維持（例外でも落とさず { ok:true, rows: [] } を返す前提）。

---

## Network / DNS に関する注意
- Temporary failure in name resolution, getaddrinfo ENOTFOUND 等が出た場合:
  - ホスト名や BASE URL を書き換えたり、怪しいワークアラウンドコードを入れない。
  - ローカル PC の DNS 問題の可能性を明示し、別環境での再現確認とログ確認を提案する。

---

## Modes（必ず判定）
入力内容を見て、以下のどれかを最初に判定する:
- [ONBOARDING] 初回の状況整理・方針確認・関連ファイルの読み込み
- [BUGFIX] テスト失敗/例外/HTTP 500 などの修正
- [FEATURE] 新機能追加/挙動変更
- [REFACTOR] 構造整理/責務分離
- [DOC] plan/*.md や README の更新・同期
- [EXPLAIN] 説明だけ（diff を出さない）

---

## 出力フォーマット（必ず守る）
1) 1段目: モード判定 と 要約
2) 2段目: 方針・設計 の箇条書き
3) 3段目: 必要な場合のみ patch(diff)
4) 4段目: 私が実行すべきコマンド/テスト一覧（PowerShell、1つのコードブロックにまとめる）

---

## Prohibited / Caution（抜粋）
- /api/range にクエリ追加・サーバ側時間フィルタ追加をしない。
- 夜窓（19:00-05:00）をサーバ側で判定/絞り込みしない。
- legacy Google Sheet / GAS を拡張しない。
- Second venues を Places API / Supabase 保存前提に戻さない（map-link を維持）。
- Secrets をハードコードしない。

---

## Good Prompt Examples
- "Update /api/range handler to keep legacy fallback but skip any time filtering; Supabase newest-first, respond asc."
- "Ensure frontend night window (19:00-05:00) stays intact while adding a new series."
- "Keep second-venue feature as Google Maps search links; no Places API, no backend changes."