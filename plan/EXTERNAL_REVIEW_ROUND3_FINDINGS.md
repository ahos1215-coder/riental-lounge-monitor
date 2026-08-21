# 外部レビュー 第3ラウンド最終レポート（2026-08-21）

対象: `9f2ea45..963a303` と、既知4件の追補修正 `5e02683` を含む現行 `HEAD`

検証時刻: 2026-08-21 14:46 JST まで

結論: **FIXED 3件 / PARTIAL 8件 / NOT FIXED 1件 / REGRESSION 0件**。

通常時の公開画面ではF5・F6・F7・F13が実際に改善し、うちF5・F6・F13は別条件も含めFIXEDと判定した。F7は障害時の5分slot境界に同じ線分断が残るため、指定された判定定義に従いPARTIALとした。一方、F3は文書化された本番既定経路では完了結果が外部へ返らず、F1・F8・F14は修正後の定期実行をまだ一度も通っていない。F4はGunicorn再生成で制限状態が消え、F10は19時切替時の非同期応答競合、F11は店舗画面の別入口、F15は現役契約文書に同じ矛盾が残る。

## 検証方法と制約

- 公開サイトの生HTML、ハイドレーション後DOM、公開API、公開GitHub Actions APIをGETで確認した。外部POST、workflow dispatch、デプロイ、400リクエスト試験は行っていない。
- 禁止された `scripts/score_forecasts.py`、`scripts/snapshot_forecasts.py`、publish処理は実行していない。git commit / push / branch操作も行っていない。
- `gh run list` は未認証だったためログインせず、公開GitHub REST APIへ切り替えた。
- レビュー開始後、許可コマンドとして対象pytestを一度実行したところ、collection中の `oriental/config.py:8-17` が `.env` / `.env.local` を自動ロードし得ることが判明した。秘密値は画面・ログへ出力されず、内容を手動で閲覧もしていないが、以後はPython import、pytest、Vitest、tscをすべて停止し、静的確認と公開GETだけに限定した。`test_api_rate_limit.py` とF3対象は `lightgbm` 不足でcollection停止、依存しないF8/local対象67件とfrontend対象71件は停止指示前に成功した。この環境ではテスト再実行を証拠の中心にしていない。

---

# 第1部: 12件の判定表

| ID | 判定 | 本番経路を含む根拠 | 実際に使ったコマンド / URL |
|---|---|---|---|
| F5 | **FIXED** | `frontend/src/components/store/LatestForecastSummaryCard.tsx:98-111,209-243` は完了夜を実測表記にし、進行中かつ `forecastStatus != ok` ならハイライト自体を出さない。姉妹SSRも `frontend/src/lib/store/ssrSummary.ts:146-182` で同じ条件。本番の渋谷は「この夜の実測ハイライト（要点）」だった。 | `https://www.meguribi.jp/store/shibuya` を実ブラウザで表示 |
| F6 | **FIXED** | `frontend/src/lib/supabase/blogDrafts.ts:404-454` は上限200、`target_date desc → updated_at desc nullslast → created_at desc` の順で取得して店舗ごとに先勝ち。本番dailyは42店、重複0、先頭 `target_date=2026-08-20`。weeklyも42店、重複0。 | `https://www.meguribi.jp/api/reports/list?type=daily` / `?type=weekly` をGET |
| F11 | **PARTIAL** | 一覧は `frontend/src/app/api/reports/list/route.ts:14-29` と `frontend/src/app/reports/reports-client.tsx:118-158,359-369` で503と空を区別する。ただし追補した `frontend/src/app/api/reports/store-summary/route.ts:27-38` の503を、`frontend/src/app/store/[id]/StorePageClient.tsx:113-130,217-227` が無視する。店舗画面では障害時も初期 `weekly:null` のままカードが消え、「週報なし」と区別できない。 | `rg -n "store-summary|body.ok|weekly" frontend/src/app/store frontend/src/app/api/reports`; `https://www.meguribi.jp/reports` を実表示 |
| F13 | **FIXED** | `frontend/src/components/ui/FadeIn.tsx:38-66` と `home/HomeHero.tsx:19-82` の `immediate` が公開SSRにも反映。本番生HTMLはH1、説明、CTAの親が初期可視で、`opacity:0` は下部4箇所だけ。ハイドレーション後H1もopacity 1。 | `Invoke-WebRequest https://www.meguribi.jp/` でstatus 200、H1抽出、`opacity:0` 4件を確認；実ブラウザでも確認 |
| F7 | **PARTIAL** | `frontend/src/lib/compare/compareSeries.ts:29-35,44-56,96-136` は5分slotへ丸めてから系列を結合。本番比較で実測2系列のSVG pathが連続し、公開rangeの渋谷×相席屋渋谷120組は全て同じ5分slot、書込差8〜12秒だった。ただし5分超の遅延や固定bucket境界をまたぐjitterで店舗ごとのslotがずれると、同じ線分断が残る。指定の「別条件で同じ症状」に該当するためPARTIAL。 | `https://www.meguribi.jp/compare?stores=shibuya,shinjuku`; `https://www.meguribi.jp/api/range_multi?stores=shibuya,ay_shibuya&from=2026-08-20&to=2026-08-21&limit=300` |
| F10 | **PARTIAL** | 夜窓・日付見出し・時刻比例軸は `frontend/src/app/compare/compare-client.tsx:221-278`、`CompareChart.tsx:104-138` どおり本番で直った。しかし19時追補の `compare-client.tsx:127-135,231-305` には旧夜fetchのabort/世代確認がない。切替後、新夜応答より遅れて旧夜応答が返ると、見出しは新夜、系列は旧夜へ再上書きされる。最大60秒の検知遅延もある。 | 上記compare URLを実表示；`rg -n -C 5 "hasNightRolledOver|Promise.all|setStoreDataMap" frontend/src/app/compare/compare-client.tsx` |
| F1 | **PARTIAL** | `scripts/snapshot_forecasts.py:310-345` は不完全成果物を `_partial/` のみに保存しexit 1、`scripts/score_forecasts.py:698-705` は正規snapshot不在を失敗にする。データ防御は妥当。ただしfix後の18:10 snapshot / 翌朝scoreはまだ本番0回で、人への通知も任意Webhook未設定時に成功扱いとなる。さらに `snapshot_forecasts.py:103-112,316-329` は逃がし弁で期待集合を空にすると空成果物をcomplete扱いできる。 | 公開Actions API `.../actions/workflows/forecast-accuracy-track.yml/runs?per_page=30`; `rg -n "SNAPSHOT_ALLOWED_MISSING|expected_slugs|complete" scripts/snapshot_forecasts.py` |
| F3 | **NOT FIXED** | `oriental/routes/tasks.py:54-80,95-122` の結果集計自体は正直になった。しかし本番既定asyncは `tasks.py:289-319` で常に202・`ok:true,status:running`、完了後 `/status` も `tasks.py:333-337` のトップレベル `ok:true` 固定。`plan/RUNBOOK.md:150-152` の登録例はクエリ無しで、status pollingも永続run recordもないため、文書化された本番経路では途中死・部分失敗がcronへ返らない。 | `https://riental-lounge-monitor.onrender.com/tasks/multi_collect/status` と `https://riental-lounge-monitor.onrender.com/tasks/multi_collect?mode=sync` を無認証GET（各401、設定変更なし）；`rg -n "multi_collect|mode=sync" plan docs tests` |
| F8 | **PARTIAL** | 日次 `scripts/monitor/check_daily_published.py:52-60,99-171`、週次 `check_weekly_published.py:51-59,129-252` と各workflowの `STRICT_ALL_STORES=1` 配線は正しい。ただしfix後のscheduled runはまだ0回。ローカル `scripts/local_report_job.py:605-623,749-752` のexit 1/2も、`docs/LOCAL_LLM_SETUP.md:103-107` のPython直起動では誰も通知・記録していない。 | 公開daily/weekly workflow runs APIをGET；`https://www.meguribi.jp/api/reports/list?type=weekly` で古いKyoto行を確認 |
| F14 | **PARTIAL** | 現行 `scripts/generate_weekly_insights.py:1568-1574` はJST日付を使い、静的には正しい。しかし公開weeklyは41店が `target_date=2026-08-18`、Kyotoが `2026-07-28`。修正後の水曜06:30 JST主経路は未実行で、PC側checkoutも確認不能。次回2026-08-26実行後の `target_date=2026-08-26` が本番確定条件。 | `https://www.meguribi.jp/api/reports/list?type=weekly` をGET |
| F4 | **PARTIAL** | 行数上限は `oriental/routes/data_range.py:260-338` と `oriental/utils/stores.py:143-181` どおり本番422で有効。短時間の300/分も有効。しかし制限状態は `oriental/routes/common.py:129-180,237-267` のプロセス内メモリで、`Procfile:15-28` は1,500+0〜200要求ごとにworkerを再生成する。Gunicorn gthreadはWSGI呼出し前に要求数を加算するため429も再生成を進め、新workerでbucketと計器が空になる。400件試験はこの閾値へ届かない。 | `.../api/range_multi?stores=shibuya,shinjuku,ueno&limit=6000` → 422；`.../healthz` → 200 / rate limit enabled；Gunicorn 23 sourceと公式settingsをGET |
| F15 | **PARTIAL** | 修正対象の入口文書は実装と一致したが、`plan/README.md:13-24,47` が現役契約として案内する `plan/API_CONTRACT.md:5,10,24,79-90` は今も `store/limit` のみ、`from/to` は契約外と断言し、`plan/API_CURRENT.md:4,29` もそこを正本参照する。「CLAUDE.md §3へ一本化」は未達。 | `rg -n "API_CONTRACT|from|to|クエリ" CLAUDE.md README.md plan -g '*.md'` |

## 判定数

- **FIXED**: F5, F6, F13
- **PARTIAL**: F1, F4, F7, F8, F10, F11, F14, F15
- **NOT FIXED**: F3
- **REGRESSION**: なし（ただしF10追補に残る非同期競合はV10参照）

---

# 第2部: V1〜V10への回答

## V1. F3の途中死回収は本番経路で効くか

**結論: 文書化された既定経路では効かない。F3は NOT FIXED。**

`tests/test_collect_task_outcome.py:106-140` のHTTP結果テスト3本は全て `?mode=sync` で、asyncテストは内部関数を直接呼ぶ。対して既定asyncの初回レスポンスは常に202/runningであり、完了結果ではない。さらに `/status` はプロセス内状態なのでworker再生成で消え、トップレベル `ok` も失敗時にtrueのままである。

本番cron-job.orgの実登録はリポジトリ外で閲覧できないため、「実際のURLにsyncが無い」とまでは断定できない。ただし正本の登録例はクエリ無しで、pollerも見つからない。少なくとも現行リポジトリだけでは完了失敗を外部へ渡す鎖が完成していない。

最小修正は、cronのtimeout内で終わるならsyncを既定にして、部分失敗・例外をHTTP非2xxにすること。asyncを維持するなら、`task_id / started_at / completed_at / expected / success / fail` をDBへ永続化し、PC・workerと独立した監視が「期限内に完了行がない」ことも失敗にする。プロセス内status pollingだけでは「プロセスごと死んだ」を検出できない。

確信度: **コードと文書は高、cron-job.org実設定は情報不足**。

## V2. F4はworker再起動で記憶を消せるか

**結論: 経路は実在する。**

Gunicorn公式は `max_requests > 0` で処理要求数到達後にworkerを再起動すると説明している。23.0.0のgthread実装はWSGIアプリ呼出し前に要求数を加算するため、Flask内で返す429も件数に含まれる。現行は1workerなので、再生成のたびに全rate bucketが消え、`oriental/__init__.py:80-93` のモデルpreload threadも再開する。

- [Gunicorn 23 settings: max_requests](https://docs.gunicorn.org/en/stable/settings.html#max-requests)
- [Gunicorn 23 gthread source](https://raw.githubusercontent.com/benoitc/gunicorn/23.0.0/gunicorn/workers/gthread.py)

本番の1,500〜1,700要求閾値では、300通過後に1,200〜1,400件を429にすれば同じ60秒内でも新workerの次の300件が通り得る。依頼書の約50req/sなら理論上30〜34秒で到達する。これは本番DoSになるため再現していない。

`--max-requests` は過去のメモリ増加に対する安全網なので外すべきではない。制限状態を所有Cloudflare edgeまたはRedis/Upstash等のworker外へ移し、現行メモリ制限はフォールバックに残すのが妥当。重い `range_multi` は店舗数・要求行数を重みにした別枠が必要である。[Cloudflare rate limiting rules](https://developers.cloudflare.com/waf/rate-limiting-rules/)

安全なローカル再現手順（**未実行**）:

1. `.env`、`.env.local`、`secrets`が存在しないclean public checkoutをLinux/WSL/containerで用意する。
2. 非秘密の試験用設定だけで `API_RATE_LIMIT_ENABLED=1`、`API_RATE_LIMIT_PER_MIN=3`、`ENABLE_FORECAST=0`、`DISABLE_MODEL_PRELOAD=1` とし、外部DB設定は空にする。
3. 次で起動する。

```text
gunicorn wsgi:app --bind 127.0.0.1:5010 --workers 1 --threads 8 \
  --max-requests 10 --max-requests-jitter 0 --access-logfile - --log-level info
```

4. 同じ `CF-Connecting-IP: 203.0.113.10` で60秒以内に `/api/meta` を10回GETする。1〜3回目200、4〜10回目429を期待する。
5. 10回目の `Autorestarting worker` 後、60秒を待たず同じIPの次回GETが200へ戻ることを確認する。

確信度: **高（本番破壊試験だけ未実施）**。

## V3. F1の翌朝アラートは人へ届くか

**結論: schedule自体は直近30意図日すべて発火したが、人への到達は保証されない。**

`gh` CLIは未認証だったため、次の公開APIをGETした。

`https://api.github.com/repos/ahos1215-coder/riental-lounge-monitor/actions/workflows/forecast-accuracy-track.yml/runs?per_page=30`

| 指標 | 実測 |
|---|---:|
| 意図日 2026-07-22〜08-20 | 30日 |
| schedule runの欠落 | 0日 |
| success / failure | 20 / 10 |
| 起動遅延 | 最小20分 / 中央55分 / 最大232分 |
| 最新run | 2026-08-20 21:37:54 UTC、F1 fix前SHA |

従って別workflowの8.3%欠落をaccuracy scheduleへ一般化するのは誤りで、問題の中心は通知終端である。failure runではnotify jobがsuccessでも、`.github/workflows/notify-on-failure.yml:35-38` はWebhook未設定時にexit 0、curlも非2xxを確実にjob failureへしない。`scripts/_ops_notify.py:49-64` とreusable workflowは同じ任意Webhookに依存し、独立した二重網ではない。

費用対効果が最も高いのは、実際に読むLINE等の1系統へ集約し、未設定・非2xxを監視job失敗にし、定期canaryで「送信コードが走った」ではなく「受信した」を確認すること。GitHub失敗メールはバックアップとして残す。

確信度: **Actions履歴は高、Webhook設定とメール閲覧状態は確認不能**。

## V4. 通常利用者全員が1バケットという設計は妥当か

**結論: 前提が正確ではない。実際はVercel egress IPごとの共有bucket。**

`frontend/src/lib/api/proxyBackend.ts:55-60` は利用者IPをBackendへ転送しないため、Renderが見るのはVercelの送信元である。ただしVercel公式によれば既定のFunctions outboundは単一固定IPではなく動的IPプールで、Static IP設定の有無は外部Dashboardを見ないと分からない。

- [Vercel: outbound IP allowlisting](https://vercel.com/kb/guide/how-to-allowlist-deployment-ip-address)

よって複数egressなら攻撃カウンタも分散し、同じegressへ利用者が集中すれば無関係な利用者が429を受ける。`/healthz` の `max_count_in_window=21` も、`common.py:151-190` が期限切れbucketを除去せず、worker再生成で全消去し、blocked総数やprocess generationを持たないため「平常時の永続最大」とは言えない。

300/分を盲目的に上げるべきではない。Vercel proxyを署名付きヘッダ等で識別して直アクセスと別bucket/別上限にし、利用者IPを転送するならその値自体を署名する。`range_multi` は要求コストで重み付けし、blocked数・現在窓・process世代を観測可能にする。なおFrontend側 `frontend/src/lib/rateLimit/apiRateLimit.ts:30-85` も実装はmodule内Mapだけで、複数Vercel instance間では共有されない。

確信度: **コードとVercel既定仕様は高、当該projectのStatic IP設定は情報不足**。

## V5. F8のローカルexit codeは誰か見ているか

**結論: 現在の自動検知としては実質未使用。**

`scripts/local_report_job.py:605-623` は成功0、失敗1、carry-overのみ2を返すが、リポジトリ内のTask Scheduler登録はPython直起動で、`LastTaskResult`、`$LASTEXITCODE`、wrapperの監視・通知がない。したがってexit code強化はプロセス契約としては有用でも、現状ではGHAのSupabase監視と比べて検知網になっていない。

意味を持たせる最小追加は、wrapperが終了値とrun時刻・成功/失敗/carry-over件数を耐久的なrun recordまたは通知へ渡し、最後に同じcodeで終了すること。ただしPC電源断時はwrapperも動かないため、独立GHA監視は残す。

確信度: **リポジトリ内は高、実Task Scheduler設定は情報不足**。

## V6. F7の固定5分slotは障害時も妥当か

**結論: 現行の通常経路では妥当だが、障害条件では同じ症状が残るため判定はPARTIAL。可変幅化は勧めない。**

渋谷×相席屋渋谷の120組は全て同じslotで、書込差8〜12秒だった。可変幅は障害の夜だけ時間分解能を変え、別収集cycleまで同じcellへ潰すため比較意味が不安定になる。

ただし5分超の遅延や固定bucket境界をまたぐjitterでは、同じ症状が再発し得る。恒久策は収集時に `collection_run_id` または予定収集時刻を持たせ、そのIDで結合すること。そこまで行わない間はspreadとcross-slot率を監視し、発生時に比較精度低下を表示するのが安全である。

確信度: **通常本番は高、障害時の実発生頻度は未測定**。

## V7. F11 / F13で最小限固定すべきテスト

1. Route単体: `fetchAllLatestPublishedReports()` を `{items: [], failed: true}` に差し替え、GETが503、`cache-control:no-store`、`ok:false` を返すこと。
2. Client統合: Playwrightでdailyだけ503、weeklyは200へinterceptし、dailyだけ失敗カード、weeklyは正常カードになること。加えて片側network rejectも1件置く。
3. F13 SSR: JavaScript無効のPlaywrightで `/` を開き、H1・説明・CTAがvisibleで祖先opacity 1であること。純粋関数テストではframer-motion SSRと `immediate` の付け忘れを検出できない。

本番raw HTMLは今回確認したため現状はFIXEDだが、上記が再発防止の最小線である。

確信度: **高**。

## V8. `Promise.allSettled` にする価値

**結論: 価値はあるが、依頼書の「片方503で両方失敗」は起きない。**

`fetch()` はHTTP 503ではrejectしない。`reports-client.tsx:127-151` は各responseを別々にparseするため、dailyが503、weeklyが200ならdailyだけfailedになる。両方failedになるのは片方がnetwork error、abort、JSON parse例外でrejectし、`Promise.all` 全体が `catch` へ入る場合である。

`Promise.allSettled` はその例外時にも成功側を残せるため小さい改善価値はあるが、503本線の不具合ではなく優先度は低い。

確信度: **高**。

## V9. Kyotoの3週間超carry-overをどう検知するか

**結論: 現在のKyotoは毎週carry-over upsertされた行ではなく、古い固定行が残存している。新F8なら次回runで検出する。**

公開値は `target_date=2026-07-28`、`updated_at=2026-07-28T21:36:19Z`、全体42件。新週次monitorの `check_weekly_published.py:149-199` は8日超staleとして失敗にするが、fix後runはまだない。

別に、意味上のcarry-overを見逃す実装がある。`scripts/generate_weekly_insights.py:1376-1381` は毎回現在時刻を `payload.generated_at` に入れ、`:1469-1477` は旧本文だけをコピーする。次回の鮮度判定 `:448-450` は新しい `generated_at` を見るため、旧本文の実年齢が毎週リセットされ、21日上限と `updated_at` 監視をすり抜けられる。

本文の出所時刻をcarry-over時に変えない `commentary_generated_at`、元 `target_date`、連続carry回数、直近失敗理由を別に保持し、最初のcarryを警告、連続2回または本文年齢超過を失敗にする必要がある。

確信度: **公開実測・コードとも高**。

## V10. 8コミットが新しく壊したもの・境界値

今回確認できた主要な残留境界は次の3点である。

1. **F10の19時応答競合（高）**: `compare-client.tsx:127-135,231-305` は旧requestをcancelしない。旧→新を発行し、新→旧の順にresolveすると旧夜が最後に残る。`AbortController` とrequest generation / `requestNightYmd` 一致確認を併用し、fake timer + deferred Promiseで固定すべき。19:00直後の最大60秒窓も、fetch開始前に現在nightを再計算すれば消せる。
2. **F1の空期待集合（中）**: `SNAPSHOT_ALLOWED_MISSING` で全slugを除くと `missing=[]` となり、空canonicalをcomplete扱いできる。期待集合非空と、逃がし弁の最大件数/未知slugを検証してから昇格すべき。
3. **F14の境界テスト盲点（中）**: `tests/test_generate_weekly_insights_main.py:50-57` の固定時刻は12:00 UTCでUTC/JSTが同日であり、旧UTC実装へ戻しても通る。火曜21:30 UTC＝水曜06:30 JSTを固定するテストが必要。

F6には完全同値行の最終tie-breakerがないが、現行の `updated_at / created_at` と公開42件では実害を確認していない。上記以外に高確信度の新規REGRESSIONは見つからなかった。

---

# 第3部: 「テストは緑だが本番では効かない」経路差の棚卸し

| 対象 | テストが叩く経路 | 本番が叩く経路 / 抜ける条件 | 今回の補完 |
|---|---|---|---|
| F1 snapshot | mockしたBackend/Storage、期待集合の単体条件 | Windows Task Scheduler、実Backend、実Storage、escape env、18:10時点 | fix後runがまだなく未証明 |
| F1 alert | `_alert()` 呼出し・exit 1 | 任意Webhook未設定、非2xx、未読GitHub mail | Actions 30日履歴をGET。配信成功は未証明 |
| F3 HTTP | `?mode=sync` のbody検証 | 文書上は既定async 202、cronはstatusをpollしない | 本番無認証GETと文書・routeを突合。NOT FIXED |
| F3 background | 内部関数直接呼出し | daemon thread、worker recycle、process-local status | durable completion recordなし |
| F4 limiter | 単一Flask `test_client` / 単一 `create_app` | Cloudflare→Render→Gunicorn、1,500件でworker再生成 | 少数本番GETとGunicorn一次資料で穴を確認 |
| F4 client IP | テストが `CF-Connecting-IP` / XFFを手入力 | Cloudflareが付与し、Vercelは動的egress pool | 400試験のCF修正は有効。ただし共有単位は固定1IPでない |
| F4 health | 同一app内でcount増加だけ確認 | bucket期限切れ、process再生成、blocked累計なし | 平常時21を長期指標として使えない |
| Frontend rate limit | 同一module Map、fetch stub | Vercel複数instance、CDN HIT/MISS、動的egress | 本番逐次試験は同一warm instanceだけを確認 |
| F5 | builder/SSR helperの分岐 | 完了夜、進行夜、forecast障害、SSR/CSR二入口 | 完了夜は本番確認、障害分岐は静的確認 |
| F6 | Supabase URL/row mock | 実DB42店、固定row、null updated_at | 公開daily/weeklyで件数・順・重複を補完 |
| F7 | 合成した秒ずれ | GAS/Supabase遅延、5分bucket境界、複数brand | 通常本番120組を確認。障害時は未再現 |
| F10 | `hasNightRolledOver()` 純粋関数 | timer、重複fetch、旧新responseの逆転 | 実画面の通常夜は確認、19時raceは未固定 |
| F11 | data helper / response構造 | Next route、network reject、React failure表示、店舗別caller | 一覧は修正、store-summary callerはエラーを捨てる |
| F13 | `initialProps` 等の純粋関数 | framer-motion SSR、HomeHero prop配線、JS無効 | raw HTMLとhydrated DOMを直接確認 |
| F8 monitor | fake row/setとexit code関数 | scheduled GHA、実Supabase、通知終端、Windows exit消費 | fix後schedule 0回。ローカルexitは未消費 |
| F14 | UTC/JSTが同日の固定時刻 | 水曜06:30 JST＝火曜21:30 UTC、PC checkout | 公開成果物はまだ旧火曜。現テストは境界を踏まない |
| Weekly carry-over | rowの `updated_at` / `generated_at` | 古い本文を新payloadへ移して時刻だけ更新 | 意味上の本文年齢を監視できない |
| F15 docs | 自動テストなし | 読者が推奨読了順で `API_CONTRACT.md` を読む | 入口5本は直ったが専用契約が逆のまま |

今回の共通パターンは、関数の戻り値だけをテストし、**その値を次に誰が読むか、プロセス再生成後も残るか、定期実行が本当に新コードを通ったか**を検証していないことである。

---

# 第4部: オーナー向けの一言

12件をまとめて「本番で修正済み」とは、まだ言えません。  
現時点で信用してよいのは3件、8件は条件付き、F3は本番の既定経路では未修正です。  
次に確かめるべきは、修正後の定期実行と通知到達、worker再起動、19時境界を含む経路試験です。
