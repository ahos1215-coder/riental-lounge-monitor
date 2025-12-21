# DECISIONS
Last updated: 2025-12-17 / commit: d4538a0

## Decision 2025-12-17: Supabase `logs` を唯一の Source of Truth にする

**決定内容**
- 観測データの source of truth は Supabase `logs` とする。
- Google Sheet / GAS は legacy fallback とし、機能拡張しない。

**理由**
- 主系データソースを Supabase に統一し、運用/拡張の基準を明確にするため。

**影響範囲**
- バックエンド: 取得・保存の主系が Supabase `logs` になる
- 運用: 収集/監視の確認先が Supabase `logs` になる

**補足**
- fallback 経路（Sheets/GAS）は「互換維持」までに留める。

## Decision 2025-12-17: レイヤリングは Supabase -> Flask -> Next.js（proxy）に固定する

**決定内容**
- 基本構成は「Supabase -> Flask API -> Next.js（Next API routes proxy）」を正とする。
- フロントから Supabase へ直接アクセスさせない。

**理由**
- 責務分離（UI とデータ取得/保存）を維持するため。

**影響範囲**
- フロント: `frontend/src/app/api/*/route.ts` 経由で backend を呼ぶ
- バックエンド: 外部公開 API の窓口として振る舞う

**補足**
- 接続先は `BACKEND_URL`（env）で切り替える（値はコードに書かない）。

## Decision 2025-12-17: 夜窓（19:00-05:00）の絞り込みはフロントで行う

**決定内容**
- 夜窓（19:00-05:00）の判定/絞り込みはフロントエンド（`useStorePreviewData.ts`）で行う。
- Backend/Next API routes に同等の時間ロジックを入れない。

**理由**
- `/api/range` を生データ提供に留め、表示窓を UI 側で柔軟に扱えるようにするため。

**影響範囲**
- フロント: 表示窓の計算と抽出を実装・保守する
- バックエンド: 時間窓変更に追従しない

**補足**
- 「過去窓」表示はフロントの `limit` 調整で行う。

## Decision 2025-12-17: `/api/range` は `store` + `limit` のみを公開契約とする

**決定内容**
- `/api/range` の公開契約は `store`（または `store_id`）と `limit` のみに固定する。
- `from/to` 等のクエリ追加やサーバ側時間フィルタ追加はしない。

**理由**
- 互換性維持と、フロント専任の夜窓責務を崩さないため。

**影響範囲**
- バックエンド: `/api/range` の I/F を固定
- フロント: 必要点数は `limit` で取得し、窓絞り込みはフロントで実施

**補足**
- Supabase へは `ts.desc` で問い合わせ、返却は `ts.asc` に整列する前提も維持する。

## Decision 2025-12-17: 二次会スポットは map-link 方式を本流に固定する

**決定内容**
- 二次会スポットは「ジャンル → Google Maps 検索リンク生成（map-link）」を本流とする。
- Places API を必須にした収集・保存型の仕様に戻さない。

**理由**
- コスト/運用負荷を増やさず、UI を軽量に保つため。

**影響範囲**
- フロント: `secondVenueMapLinks.ts` が正（Places API 依存を前提にしない）
- バックエンド: `/api/second_venues` は補助/将来用（例外でも `{ ok:true, rows: [] }`）

**補足**
- Places API を使うとしても optional（`/tasks/update_second_venues`）に留める。

## Decision 2025-12-17: Forecast は `ENABLE_FORECAST=1` のときのみ有効化する

**決定内容**
- `/api/forecast_today` と `/api/forecast_next_hour` は `ENABLE_FORECAST=1` のときのみ有効。
- 無効時は `503 { ok:false, error:"forecast-disabled" }` を返す。

**理由**
- 予測機能を optional にし、主系（実測）の可用性を優先するため。

**影響範囲**
- バックエンド: forecast ルートは guard を維持する
- フロント: forecast 無し（503/空配列）でも表示を継続する

**補足**
- 予測の有無で `/api/range` 契約や夜窓責務は変えない。

## Decision 2025-12-17: 本番収集の入口は `/tasks/multi_collect` を正とする

**決定内容**
- 収集の主系入口は `GET /tasks/multi_collect`（alias: `GET /api/tasks/collect_all_once`）とする。
- `/tasks/tick` は単店舗 + ローカル/GAS向けのレガシーとして維持する（Supabase `logs` insert 経路ではない）。

**理由**
- 収集の実行単位を「全店舗」に統一し、監視・運用を単純化するため。

**影響範囲**
- 運用: cron は `/tasks/multi_collect` を叩く前提で組む
- バックエンド: `/tasks/tick` の互換は維持する

**補足**
- 5分間隔/19:00-05:00 は運用（cron）側で制御する。

## Decision 2025-12-17: Secrets をコード/Git に含めない

**決定内容**
- Supabase URL/Key、Render/Vercel の各種キー等の secrets をコードに書かない。
- `.env` / `frontend/.env.local` はコミットしない。`NEXT_PUBLIC_*` に秘密値を入れない。

**理由**
- 漏洩リスクを避けるため。

**影響範囲**
- フロント/バックエンド/運用: env 管理が前提になる

**補足**
- docs には「キー名のみ」を書く（値は書かない）。

## Decision 2025-12-17: 無料枠/低コスト前提で必須依存を増やさない

**決定内容**
- 必須依存は Supabase（logs）/ Flask backend / Next frontend に留める。
- 課金が発生しやすい外部 API（例: Places API）を「必須」にしない。

**理由**
- 継続運用のコストを増やさないため。

**影響範囲**
- フロント: map-link 等で成立する UX を優先する
- バックエンド: optional 機能は env で gate する

**補足**
- 必須依存を増やす場合は `plan/ARCHITECTURE.md` / `plan/API_CONTRACT.md` の前提を再確認する。
