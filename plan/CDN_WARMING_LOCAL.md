# CDN_WARMING_LOCAL — CDN warming の実行主体をローカルへ移した経緯とURL仕様

## 背景（測定結果）

`.github/workflows/warm-cdn.yml`（GitHub Actions `schedule:` 10分毎・19:00〜23:50 JST）を
2晩実測した結果、想定60回の発火に対し実際に走ったのは **5回（8.3%）**、間隔が1.5〜3時間
空くこともあった。GitHub Actions の `schedule` トリガーは「最短5分間隔の目安」であって
厳密な保証がなく、GitHub 側の負荷次第で遅延・間引きされる既知の制約がある。結果として
CDN warming は事実上機能しておらず、実訪問者がコールドAPI（1-9秒）を引き続けていた。

## 決定（オーナー承認）

プライマリの実行主体を、既に `MEGRIBI-daily-evening` / `MEGRIBI-daily-late` /
`MEGRIBI-weekly` を安定運用しているオーナーの24時間稼働 Windows PC の Task Scheduler に
移す（`docs/LOCAL_LLM_SETUP.md` と同じ機体・同じ運用パターンの前例あり）。

- **プライマリ**: Task Scheduler タスク `MEGRIBI-warm-cdn` → `scripts/warm_cdn_local.py`
  （10分毎・19:00〜23:59 JST）
- **バックアップ**: `.github/workflows/warm-cdn.yml`（スケジュールそのまま維持。GHA の
  cron がたまたま時刻通りに発火した回だけ追加で温める日和見運用）
- **将来案（今回は対象外）**: cron-job.org 等の外部スケジューラでの二重化。オーナーの
  外部アカウント設定が必要なため保留。

## URL仕様（クライアントコードと完全一致させる）

CDNキャッシュはURLの完全一致（パス+クエリ文字列）がキーなので、以下はすべて実際の
クライアントコードを読んで抽出した形（推測ではない）。ソース:

- `frontend/src/app/hooks/storePreviewSnapshot.ts` — `RANGE_LIMIT_BY_MODE`
  (today=240, yesterday=1200)、`computeNightBaseDate` / `computeSelectedNightBaseDate` /
  `isNightCompleted` / `nightDateYYYYMMDD`
- `frontend/src/app/hooks/useStorePreviewData.ts` — 店舗詳細ページの range/forecast URL
- `frontend/src/app/stores/stores-list-client.tsx` — 一覧ページ（12件/ページ、フィルタ
  無しのデフォルト表示）の `range_multi` / `forecast_today_multi` / `megribi_score`
- `frontend/src/app/store/[id]/StorePageClient.tsx` — 「ほかの店舗を見る」欄
  (`digestStores`: haversine距離で最寄り4店舗、店舗ごとに固有のCSV)
- `frontend/src/app/home-client.tsx` — トップページの `megribi_score`（無条件）と
  フォールバック店舗の `range`
- `frontend/src/app/config/stores.ts` — `distanceKm`（haversine, R=6371）

### カテゴリ別内訳（43店舗ベース）

| カテゴリ | 本数/回 | 例 |
|---|---:|---|
| 店舗詳細: range（今日+昨日） | 43×2=86 | `/api/range?store=X&from=...&to=...&limit=240\|1200` |
| 店舗詳細: forecast（今日+昨日） | 43×2=86 | `/api/forecast_today?store=X`, `/api/forecast_snapshot?store=X&date=YYYYMMDD` |
| 一覧ページ 1〜4ページ目 | 4×3=12 | `range_multi` / `forecast_today_multi` / `megribi_score` |
| 関連店舗（店舗ごと固有CSV） | 43 | `/api/range_multi?stores=<最寄り4店>&limit=48` |
| トップページ | 2 | 無条件 `megribi_score`、先頭店舗の `range?limit=48` |
| **合計** | **229** | |

`scripts/warm_cdn_local.py`（プライマリ）はこの229本すべてをカバーする。
`.github/workflows/warm-cdn.yml`（バックアップ）は関連店舗の43本（bashでhaversine距離
計算を再実装するのは壊れやすく割に合わない）を除いた186本をカバーする。

### 夜窓の日付計算の単純化

`computeNightBaseDate` は「JST 19:00 より前ならベース日を1日戻す」分岐を持つが、両方の
warmer とも実行窓が JST 18:55〜24:05（GHA 側は 19:00〜23:50）に限定されているため：

- `scripts/warm_cdn_local.py` は分岐を関数として忠実に実装（18:55-18:59 の極小窓のみ
  この分岐が働く可能性があるが、実運用ではほぼ発生しない安全側の実装）。
- `warm-cdn.yml`（bash）は「19:00 以降にしか走らない」ことを前提に、ベース日=当日で
  単純化（コメントに明記済み）。手動 `workflow_dispatch` を19時より前に叩いた場合は
  この単純化が外れる点に注意。

「昨日」タブの予測は、両 warmer の実行窓では常に `isNightCompleted` が真になるため、
`forecast_snapshot?date=<JST昨日 YYYYMMDD>` を使う（`forecast_today` ではない）。

## レート制限に関する注意（実装時に発見）

`frontend/src/lib/rateLimit/apiRateLimit.ts` の `rateLimit(req, prefix, N)` が
`frontend/src/app/api/*/route.ts` すべてに掛かっている（IP×prefixのスライディング
ウィンドウ、既定60/分。`range_multi`/`forecast_today`/`forecast_snapshot`は30/分、
`forecast_multi`は20/分）。オーナーPCのIPはこのバケットの唯一の消費者だが、1回の
warmingパスで `range` プレフィックスだけで約87本ヒットするため、素朴に0.15-0.25秒間隔
で撃つと1分未満でパスが終わり、1つの60秒ウィンドウに全リクエストが収まって自分自身の
レート制限（429）に引っかかる。`scripts/warm_cdn_local.py` は既定 `WARM_SLEEP_SECONDS=0.35`
でパス全体を1分強に広げ、各prefixの分あたり予算を大きく超えないようにしている
（`WARM_SLEEP_SECONDS` 環境変数で調整可）。429を含む個別失敗はカウントされるだけで
パス自体は中断しない。

## Task Scheduler 登録（オーナー実行・未登録）

```powershell
$py = "C:\Users\ahos1\AppData\Local\Programs\Python\Python314\python.exe"
$root = "C:\Users\Public\共有データ系\ORIENTAL\ORIENTAL\riental-lounge-monitor-main"

schtasks /Create /TN "MEGRIBI-warm-cdn" /SC DAILY /ST 19:00 /RI 10 /DU 0005:00 /F `
  /TR "$py $root\scripts\warm_cdn_local.py"

$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -AllowStartIfOnBatteries `
     -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
Set-ScheduledTask -TaskName "MEGRIBI-warm-cdn" -Settings $s
```

`/SC DAILY /ST 19:00 /RI 10 /DU 0005:00` = 毎日19:00起点、10分毎に5時間分繰り返し
（最終発火23:50）。既存の `MEGRIBI-daily-*` / `MEGRIBI-weekly` と同じく管理者権限は不要
（対話ログオンで可）。

## ログ

`scripts/warm_cdn_local.py` は `%TEMP%\warm_cdn_local_YYYYMMDD.log`
（`WARM_CDN_LOG_DIR` で変更可）に1行/URL＋パス末尾のサマリを追記する（日付が変わると
ファイル名が変わるため自然にローテーションする）。

## 未対応・将来検討

- 関連店舗43本の bash 実装（バックアップ workflow 側）— 優先度低（プライマリでカバー
  済み、backupはあくまで日和見）。
- cron-job.org 等の外部スケジューラでの三重化 — オーナーの外部アカウント設定が必要。
- range/range_multi の CDN TTL（s-maxage=240 + SWR=300 = 540秒）が10分間隔(600秒)より
  短く、理論上は間隔中に一瞬だけ完全に期限切れる隙間がある。TTLを延ばすかどうかは
  別途要検討（本タスクのスコープ外）。
