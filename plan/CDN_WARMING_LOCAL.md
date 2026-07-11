# CDN_WARMING_LOCAL — CDN warming の実行主体をローカルへ移した経緯とURL仕様

## 背景（測定結果）

`.github/workflows/warm-cdn.yml`（GitHub Actions `schedule:` 10分毎・19:00〜23:50 JST）を
2晩実測した結果、想定60回の発火に対し実際に走ったのは **5回（8.3%）**、間隔が1.5〜3時間
空くこともあった。GitHub Actions の `schedule` トリガーは「最短5分間隔の目安」であって
厳密な保証がなく、GitHub 側の負荷次第で遅延・間引きされる既知の制約がある。結果として
CDN warming は事実上機能しておらず、実訪問者がコールドAPI（1-9秒）を引き続けていた。

## 2026-07-11 追加の不具合と対処（バグ監査 rank5 / rank7）

ローカル移行後の実運用ログから、さらに2件の不具合が見つかった。

1. **rank5a: Task Scheduler タスクが「対話ログオン時のみ」で登録されていた。**
   7/10の初回発火が19:00ではなく **21:04** になり、19:00〜21:00のランプアップ帯の
   本来12回の発火が丸ごと欠落した。原因は `MEGRIBI-warm-cdn` タスクが「ユーザーが
   ログオンしているときのみ実行」（Logon Mode = Interactive）で登録されていたため
   （オーナーPCへの対話ログオンが21時頃だった）。正しくは「ユーザーのログオン状態に
   関係なく実行する」（`/RU SYSTEM`、Logon Mode = Background only）で登録する必要が
   あった。本スクリプトの以前のdocstringには「対話ログオンで問題ない」という誤った
   記述があったが、これがまさに今回の2時間遅延の直接原因だったため訂正済み
   （`scripts/warm_cdn_local.py` のTask Scheduler登録スニペット参照）。修正手順は
   下の「Task Scheduler 登録」セクション参照。
2. **rank5b: 429バーストの再発。** 実ログで `fail=34/48/44/57`（分母は229、複数パスで
   最大 ~25%）という429バーストが繰り返し観測された。`build_all_urls` の同一prefix
   分散（既存対策）だけでは不十分だったため、`scripts/warm_cdn_local.py` に3段の
   追加ペーシングを入れた（詳細は下の「レート制限に関する注意」セクション）。
3. **rank7: megribi_score の温めは判定UI OFF中は純粋な無駄だった。** `/api/megribi_score`
   が支える「判定」表示（スコアバッジ・混雑ラベル・狙い目・トップの「今夜のおすすめ
   TOP5」）は `frontend/src/lib/featureFlags.ts` の `SHOW_MEGRIBI_JUDGMENTS` で
   2026-07-10からOFF（スコアロジックが実態と不一致のため）。UIが表示されない間に
   温め続けるのはRenderバックエンドへの無駄な実処理負荷（capacity固定の壊れた
   スコア計算を毎回実行）でしかないため、`scripts/warm_cdn_local.py` /
   `.github/workflows/warm-cdn.yml` 双方から megribi_score の温めURLを削除した
   （フラグが `true` に戻ったら復元、各ファイルにコメントで復元方法を明記済み）。
   なお、フロントエンド自身が今も無条件に `/api/megribi_score` を fetch している点
   （`home-client.tsx` 等）は別バッチの担当範囲であり、本変更は「温め」側のみが対象。

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
- `frontend/src/app/home-client.tsx` — フォールバック店舗の `range`
  （`megribi_score` は2026-07-11に温め対象から削除。上の「rank7」参照）
- `frontend/src/app/config/stores.ts` — `distanceKm`（haversine, R=6371）

### カテゴリ別内訳（43店舗ベース、2026-07-11 megribi_score削除後）

| カテゴリ | 本数/回 | 例 |
|---|---:|---|
| 店舗詳細: range（今日+昨日） | 43×2=86 | `/api/range?store=X&from=...&to=...&limit=240\|1200` |
| 店舗詳細: forecast（今日+昨日） | 43×2=86 | `/api/forecast_today?store=X`, `/api/forecast_snapshot?store=X&date=YYYYMMDD` |
| 一覧ページ 1〜4ページ目 | 4×2=8 | `range_multi` / `forecast_today_multi` |
| 関連店舗（店舗ごと固有CSV） | 43 | `/api/range_multi?stores=<最寄り4店>&limit=48` |
| トップページ | 1 | 先頭店舗の `range?limit=48` |
| **合計** | **224** | |

（megribi_score削除前は229本。店舗数はハードコードではなく `stores.json` から動的に
数えるため、店舗数が変われば上記本数もそれに応じて変わる — テスト側もこの前提で
`stores.json` 由来の店舗数から本数を導出し、229/43のような固定値を書かない。）

`scripts/warm_cdn_local.py`（プライマリ）はこの224本すべてをカバーする。
`.github/workflows/warm-cdn.yml`（バックアップ）は関連店舗の43本（bashでhaversine距離
計算を再実装するのは壊れやすく割に合わない）を除いた181本をカバーする。

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

## レート制限に関する注意（実装時に発見、2026-07-11に強化）

`frontend/src/lib/rateLimit/apiRateLimit.ts` の `rateLimit(req, prefix, N)` が
`frontend/src/app/api/*/route.ts` すべてに掛かっている（IP×prefixのスライディング
ウィンドウ、既定60/分。`range_multi`/`forecast_today`/`forecast_snapshot`は30/分、
`forecast_multi`は20/分）。オーナーPCのIPはこのバケットの唯一の消費者だが、1回の
warmingパスで `range` プレフィックスだけで約87本ヒットするため、素朴に短い間隔で
撃つと1分未満でパスが終わり、1つの60秒ウィンドウに全リクエストが収まって自分自身の
レート制限（429）に引っかかる。

`build_all_urls` の同一prefix分散（related range_multiの各店舗ブロック内への
インターリーブ）が一次防御だが、実運用ログでそれでも429バースト
（`fail=34/48/44/57`、分母229、複数パスで最大~25%）が繰り返し観測されたため、
2026-07-11に3段の追加ペーシングを入れた（すべて `scripts/warm_cdn_local.py` の
定数/CLI引数/環境変数で調整可）:

| 層 | 既定値 | 環境変数 / CLI | 目的 |
|---|---|---|---|
| 基本間隔（既存） | 0.3秒（旧0.2秒から引き上げ） | `WARM_SLEEP_SECONDS` / `--sleep` | 全リクエスト間の下限フロア |
| 定期の追加ポーズ | 20リクエストごとに1.0秒 | `WARM_EXTRA_SLEEP_SECONDS` / `--extra-sleep`、`WARM_EXTRA_SLEEP_EVERY` / `--extra-sleep-every` | 定常ペーシングだけでは埋まらないよう、長めの休みを周期的に挟む |
| 429バックオフ+単発リトライ | 2.5秒 | `WARM_BACKOFF_SECONDS` / `--backoff` | 429を受けたそのURLだけ、ウィンドウが進むのを待ってから1回だけ再試行（ループしない＝最悪ケースが有界） |

429を含む個別失敗はカウントされるだけでパス自体は中断しない（ok/fail比が50%を
超えたときだけバックエンド障害を疑ってプロセスを失敗させる、既存の挙動は変更なし）。
サマリ行は `429_hit`（1回目の試行が429だった本数）と `recovered_after_retry`
（そのうちリトライで成功した本数）、`still_429_after_retry`（リトライ後もまだ
失敗だった本数）を別々に出す。

### 想定パス所要時間 と 実パス検証結果（2026-07-11、本番 www.meguribi.jp に対する実測）

ペーシングのみによる意図的な待機時間の理論値: 基本間隔 223回×0.3秒 ≒ 66.9秒 ＋
追加ポーズ 11回×1.0秒 ≒ 11秒 → 合計 約78秒（約1.3分）。これに実際のリクエスト
往復時間が加わる。429が発生した分だけバックオフ2.5秒＋リトライ往復が追加されるが、
単発リトライのみなので上限は `本数 × バックオフ秒数` で有界。

実際に本番へ3パス実行して検証した（`WARM_WINDOW_START`/`WARM_WINDOW_END` で窓ガードを
無効化、`--sleep`/`--backoff` 等は全て既定値）:

| パス | 条件 | total | ok | fail | 429_hit | recovered | still_429 | 所要時間 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| ① 修正後・実時刻(日中)で実行 | `now`が日中のため今日/昨日タブが両方forecast_snapshotに集中（本来の夜間窓では起きない二重負荷、下記注参照） | 224 | 195 | 29 | 42 | 13 | 29 | 243.3秒 |
| ② 修正後・夜間相当の時刻(20:00 JST)を再現 | 本来の運用と同じくforecast_today/forecast_snapshotに負荷が分散 | 224 | 224 | 0 | 0 | 0 | 0 | 92.3〜113.6秒（2回実行、以下同） |
| ③ 修正前ロジック(0.2秒間隔・バックオフ無し・megribi_score込み229本)・同じ20:00 JST相当 | 旧コードを`git show main:...`で取り出して同条件比較 | 229 | 229 | 0 | 0 | — | — | 60.1秒 |

**パス①の分析（重要）**: `WARM_WINDOW_START=00:00 WARM_WINDOW_END=23:59` で窓ガードだけ
外して実時刻のまま実行すると、`compute_night_base_date`/`is_night_completed` が
「今夜の夜セッションも既に完了済み」と判定し、本来なら「今日」タブに使われる
`forecast_today`（30/min）ではなく「今日」「昨日」の両方が `forecast_snapshot`
（同じく30/min）を使うようになり、forecast_snapshot だけで86本（43×2）に倍増する
テスト特有のアーティファクト。実際の429の内訳もこの2ラベル
（`forecast_today_snapshot` 9/43, `forecast_yesterday_snapshot` 20/43失敗）に
集中しており、`range`/`range_multi` 側は0件だった。つまりこのパスは
「本番の夜間窓(19:00-24:05)条件より厳しい人工的ワーストケース」であり、それでも
リトライ機構が18.75%の429ヒットのうち13本（31%）を回収し、最終failを12.9%まで
下げた（バグ監査で報告された最悪 `57/229`≒24.9%と同水準〜それ以下）。

**パス②・③の分析**: 現在時刻を実際の19:00-24:05窓の代表値（20:00 JST）に固定して
`build_all_urls`/`fetch_one`/ペーシングだけをそのまま呼ぶ形で比較すると、修正前
（0.2秒間隔・バックオフ無し・megribi_score込み229本）・修正後（0.3秒間隔＋周期休憩
＋429バックオフ、224本）のどちらも429は0件だった。これは検証を行った時間帯
（日中、実訪問者トラフィックが少ない）では自己衝突が起きにくいことを示しており、
バグ監査で報告された実際の悪いパス（`fail=34/48/44/57`）は「夜間ピーク帯・実訪問者
トラフィックとの同時アクセス」が主因である可能性が高い。したがって今回の変更の
本当の効果検証は、次回19:00-23:50の実運用パスのログ（`%TEMP%\warm_cdn_local_
YYYYMMDD.log`）で429件数が実際に下がったかを見て判断すること。

**結論**: いずれのパスも所要時間は最大243.3秒（約4.1分）で、10分間隔の
Task Scheduler繰り返しに対して十分な余裕がある。429ミティゲーション（ペーシング
強化＋周期休憩＋単発バックオフリトライ）は少なくとも人工的な高負荷条件下では
機能することを確認済み。実際の夜間ピーク帯での効果は次回運用パスのログで
追跡すること。

## Task Scheduler 登録（オーナー実行・要修正 — バグ監査 rank5a）

**現状の不具合**: 現在登録されている `MEGRIBI-warm-cdn` タスクは「ユーザーが
ログオンしているときのみ実行」（Logon Mode = Interactive）になっている。これが
2026-07-10の初回発火が19:00ではなく21:04にずれ、19:00〜21:00の本来12回の発火が
まるごと欠落した直接原因。正しくは「ユーザーのログオン状態に関係なく実行する」
（Logon Mode = Background only）にする必要があり、そのためには実行アカウントを
`SYSTEM`（`/RU SYSTEM`）にする。**管理者（Administrator）権限のPowerShell/コマンド
プロンプトが必要。**

### 既知の落とし穴 — `schtasks /Change /RU` は使わないこと

既存タスクに対して `schtasks /Change /TN "MEGRIBI-warm-cdn" /RU SYSTEM` を実行しても、
一見成功したように見えて **Logon Mode が "Run only when user is logged on" に
サイレントに戻ってしまう既知の不具合**が `schtasks.exe` にある（Microsoft Q&A で
複数報告あり。/RU を書き換えるとログオンタイプ設定がリセットされる）。つまり
`/Change /RU SYSTEM` では今回の不具合は直らない可能性が高い。オーナー（実行者）が
これを踏まないよう、下記のどちらかの方法を使うこと。

### 方法A（推奨）— PowerShellの `Set-ScheduledTask -Principal` で直接変更

タスクを作り直さず、プリンシパル（実行アカウント/ログオンタイプ）だけを
Task Scheduler の内部モデル経由で書き換える。`schtasks.exe` の legacy な
`/Change /RU` 経路とは別の実装なので、上記の既知不具合を踏まない。

```powershell
# 要: 管理者(Administrator)として実行
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount
Set-ScheduledTask -TaskName "MEGRIBI-warm-cdn" -Principal $principal

# 確認: Logon Mode が "Background only"、Run As User が "NT AUTHORITY\SYSTEM" であること。
schtasks /Query /TN "MEGRIBI-warm-cdn" /V /FO LIST | findstr /I "Logon Run_As"
```

### 方法B（代替）— タスクを `/RU SYSTEM` 付きで作り直す（`/Create /F`）

方法Aが使えない環境向けの代替。`/Change` ではなく `/Create /F`（上書き作成）を
使う点が重要 — **作成時**に `/RU SYSTEM` を指定するのは（`/Change` と違って）
確実に動作する。

```powershell
# 要: 管理者(Administrator)として実行
$py = "C:\Users\ahos1\AppData\Local\Programs\Python\Python314\python.exe"
$root = "C:\Users\Public\共有データ系\ORIENTAL\ORIENTAL\riental-lounge-monitor-main"

schtasks /Create /TN "MEGRIBI-warm-cdn" /SC DAILY /ST 19:00 /RI 10 /DU 0005:00 /RU SYSTEM /F `
  /TR "$py $root\scripts\warm_cdn_local.py"

$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -AllowStartIfOnBatteries `
     -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
Set-ScheduledTask -TaskName "MEGRIBI-warm-cdn" -Settings $s

# 確認（方法Aと同じ）
schtasks /Query /TN "MEGRIBI-warm-cdn" /V /FO LIST | findstr /I "Logon Run_As"
```

`/SC DAILY /ST 19:00 /RI 10 /DU 0005:00` = 毎日19:00起点、10分毎に5時間分繰り返し
（最終発火23:50）。`/RU SYSTEM` の場合、`/RP`（パスワード）は不要・指定しないこと
（SYSTEMアカウントにはパスワード自体が無いため、指定しても無視されるか無駄）。

**SYSTEM実行に伴う注意点**:
- SYSTEMは通常NTFS上ほぼ全ファイルへのフルコントロールを持つため、
  `$py`（`C:\Users\ahos1\AppData\Local\Programs\Python\Python314\python.exe`、
  他ユーザーのプロファイル配下）や `$root`（共有ドライブ配下）への実行アクセスは
  通常問題にならない想定。ただし初回実行後は必ずタスク履歴/ログ
  （`%TEMP%\warm_cdn_local_YYYYMMDD.log`、SYSTEM実行時は `C:\Windows\Temp\` 配下に
  なる点に注意 — `WARM_CDN_LOG_DIR` で明示的に固定パスを指定するのも一案）で
  実際に動いたか確認すること。
- 既存の `MEGRIBI-daily-*` / `MEGRIBI-weekly` タスクは対話ログオンのままで運用中
  （このドキュメントの対象外）。`MEGRIBI-warm-cdn` だけを `/RU SYSTEM` に切り替える。

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
