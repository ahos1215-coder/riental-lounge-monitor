# 外部レビュー 進捗メモ（Codex が更新するファイル）

> このファイルは **Codex（ChatGPT）が自分のために書く引き継ぎメモ**です。
> 利用上限で中断した後、次回起動時にここを読んで続きから再開します。
> 指示書は `plan/EXTERNAL_REVIEW_2026-08-21.md`。人間（オーナー）とClaudeも状況確認のためにここを読みます。

STATUS: COMPLETE
UPDATED: 2026-08-21 14:51 JST
NEXT: 第3ラウンド完了。修正後の次回定期実行（snapshot/score、daily/weekly monitor、2026-08-26週報）をオーナー側で確認する

---

## 第2ラウンド（論点A〜Gの決着）

R2_STATUS: COMPLETE
R2_UPDATED: 2026-08-21 04:48 JST
R2_NEXT: なし（第2ラウンド報告書の確認待ち）
R2_DONE: `plan/_local/ROUND2_METRICS.md` を最初に全文読了／第2ラウンド依頼書を全文読了／公開競合・公式サービスをGETで再確認／PageSpeed Insightsをmobile・desktopで実測／公開forecast GETで42店の現行blend適用状況を確認／F2・F3・F13・F14をコードと公開HTMLで再検証／論点Aの15案、B〜Gの回答、第1回判定訂正、90日提言を `plan/EXTERNAL_REVIEW_ROUND2_FINDINGS.md` に作成／`git diff --check` 成功
R2_FINDINGS:
- 実利用は直近28日37人・リピート5人・47セッション・105PV。検索は90日4,093表示/83クリック、直近28日1,209表示/33クリック。母数は極小だが、20〜1時台の来店直前用途と、実利用者による料金試算・期間切替の1セッションは確認できる。
- 検索露出の35.5%がDaily/Weeklyで、`/stores` は1,244表示に対して1クリック。露出不足だけでなく、着地・検索意図・スニペットの不一致が強い。ただし平均順位だけを「本丸」とするには、ページ別の順位・CTR・検索意図を分解する必要がある。
- 9ヶ月・約129万行・5分×42店×男女別の履歴は、現在値一覧より「条件付きの意思決定」「似た夜の比較」「横断的な異常・機会検出」に使うと固有性が出る。
- Python全体テストは提供環境で1,053件成功した実測が共有されたため、第1回の環境制約は解消済みとして扱う。
- 第1回の「横断サービスは現在値中心で、履歴・予測はMEGRIBIだけ」という市場認識は誤り。相席なうは88店規模の履歴ヒートマップ、月次統計、季節予測、料金比較・試算まで公開している。MEGRIBIの差は横断/履歴というカテゴリではなく、5分粒度・約129万行・店舗別の天候/祝日/給料日/直近速度を含む予測を、現在値・料金・通知と一つの来店判断へ束ねられる点に絞る。
- PageSpeed公開UIの独立2回のlab計測で、トップのmobile LCPは4.4〜4.5秒、desktopは1.1秒。CrUX/field dataは母数不足で未提供。mobileのLCP要素はFadeIn内のHero説明文で、初期`opacity:0`の修正はUX/SEO交差施策として優先価値がある。ただし単発labから順位低迷の原因とは断定しない。
- `/store/[id]` と `/area/[area]` のH1/主要SSR内容はFadeInを使わず、公開raw HTMLにも`opacity:0`がない。F13の波及はトップに限定して扱う。
- 現行公開forecast 42店ではblend weight平均0.539、範囲0.454〜0.596で、下限0.15・上限0.9到達は0店。全店39/40slotでblend適用を確認した。自己参照評価の測定バイアスは確定だが、現在のweight発散実害は未確認。
- 計画済みのblend適用率と週次peak/ghost/bandだけではML成分の寄与を識別できない。配信値を変えず、blend直前のpreblend成分・baseline・served・weight/maskを同一slotでsnapshotし、翌朝に別採点するshadow評価が必要。
- F2は5分再試行と独立2時間heartbeatを踏まえ、第1回の「高」から「中」へ修正する。F3は、42店中20店の大部分のslotが欠けても全体fresh・店舗age<3日・失敗率50%未満を満たして無期限にgreenとなり得るため、データ完全性の影響として「高」を維持する。主欠陥は非同期そのものより、期待集合の永続化完了をsuccess条件にしていない点。
- F14の「一覧順・監視対象日もずれる」は根拠がなく撤回する。一覧は`created_at`、週次監視は`updated_at`/店舗集合を見るため、確認できる波及は火曜の`target_date`表示、生成JSON名、場合によってはsitemap `lastModified`に限る。重大度は中から低へ修正する。
- 8月事故の再発を1本で早期検知するなら、PC外の2時間GHAがPC last-seen、snapshot last-attempt/last-good、expected/observed/missing、generation_id一致を検査し、LINEへ通知するnight-integrity sentinel。実装順は正規snapshotの書込前完全性guard（F1）を先、その直後にsentinel/LINE、最後に週次digest。

---

## DONE（完了したフェーズと、その要約）

<!-- 例:
### P1 完了（2026-08-21 15:20）
公開サイトを利用者として一通り閲覧。第一印象を FINDINGS_SO_FAR に記録。
### P2 完了（2026-08-21 16:10）
CLAUDE.md と plan/README.md を読了。リポジトリ構成を把握。迷子になった箇所を記録。
-->

### P1 完了（2026-08-21 03:19 JST）
公開サイトをコード未読の状態で利用者として確認。PC幅（1280×720）でトップ、店舗一覧・検索、店舗詳細、3店舗比較、AI予測一覧・Daily本文、マイページを操作し、スマホ幅（約390×844）でトップ、ハンバーガーメニュー、店舗一覧・検索、店舗詳細を確認した。

- 数秒以内に「相席ラウンジ42店舗のリアルタイム男女別人数とAI混雑予測」のサイトだと理解できた。主CTAから一覧・詳細への到達も容易。
- 店舗詳細の「○分前更新」、男女別人数、実測/予測グラフ、料金試算は、来店判断に直結する情報として強い。
- 確認したスマホ画面では横方向のはみ出しはなく、メニュー・検索・カード・詳細グラフを操作できた。下部固定の「店舗一覧へ」も目的導線として分かりやすい。
- 一方、同一画面内・画面間で時刻や数値の文脈が揃わず、予測への信用を損ねる表示が複数あった。詳細は FINDINGS_SO_FAR に記録。

### P2 完了（2026-08-21 03:23 JST）
指定順どおり `CLAUDE.md` → `plan/README.md` を全文読了し、続いてルート `README.md`、`plan/INDEX.md`、`plan/CODEx_PROMPTS.md`、`plan/ARCHITECTURE.md`、`frontend/README.md`、`archive/README.md` と物理ファイル構成を確認した。

- `CLAUDE.md` は、利用者→Next.js→Flask→Supabase、5分収集、ローカルOllama、GHA ML/監視という全体像を得るうえでは非常に有効だった。
- 追跡対象は概ね Backend 38ファイル、Frontend source 232ファイル、Python tests 84ファイル、scripts 34ファイル、GHA workflows 21本。これとは別に生成済み週次Insights JSONが788ファイルある。
- 主な正本は把握できたが、入口文書間の契約矛盾、複数の読了順、未案内の旧プロトタイプがあり、「古い文書に騙されないための文書」自体を疑ってコードで再確認する必要がある。

### P3 完了（2026-08-21 03:35 JST）
Backend、Frontend、ML/バッチ、監視を静的に追跡し、P1で実見した表示不整合を実装まで結び付けた。禁止スクリプトは実行せず、秘密値・秘密ファイルも開いていない。

- Frontend: `tsc --noEmit` 成功。Vitest は 48ファイル・746テストすべて成功。
- Python: `python -m pytest -q` はローカル環境に `lightgbm` / `scipy` が無いため収集時に24エラーとなり、全体は実行不能。依存追加は行わなかった。依存しない対象へ絞ったテストは、日次carry-over・収集heartbeat 57件、blend weight・score summary・公開監視 34件、計91件が成功。
- テスト群はJST夜境界、過去事故、キャッシュ、carry-over等の回帰を細かく固定しており質は高い。一方、画面間の意味整合、比較グラフの実系列、固定行の更新順、ジョブの期待店舗集合という「経路全体」の検証が抜けている。
- 主な確定事項を下の FINDINGS_SO_FAR に追記。P4では個別修正を増やすより、個人運用として残すべき中核と捨てるべき枝を評価する。

### P4 完了（2026-08-21 03:39 JST）
`plan/VISION_AND_FUTURE.md`、`plan/ROADMAP.md`、`plan/STATUS.md`、`docs/FAILURE_MAP.md`、`docs/LOCAL_LLM_SETUP.md` と直近の公開競合を照合し、個人運用の持続可能性と事業性を評価した。

- 続ける価値はある。ただし「相席店の総合メディア」を広げ続けるのではなく、90日間だけ「今、どの店へ、いつ行くか」に答える小さな実用サービスとして検証する、という条件付き。リアルタイム人数そのものは公式・競合にもあり、差別化は横断比較、履歴、将来ピーク予測と、その信頼性に限られる。
- 現行運用は個人には重すぎる。Windows Task Scheduler 6本、ローカルOllama/GPU排他、GHA 21本、cron-job.org、Render、Vercel、Supabase、複数通知先が絡み、2026-08の障害棚卸しにはPC停止10日、空snapshot30日超、GitHub失敗メールが読まれない実績が記録されている。
- 次の3ヶ月で1つだけ行うなら「信頼性リセット」。期待42店を一つの集合として検証するend-to-end canary、snapshot/予測の世代と鮮度の明示、失敗時に必ず届く通知先1つを先に完成させる。AI記事量産、Editorial/X自動化、v2 shadow・自己更新blend、Web Push、課金、ブランド拡大は一旦止める。
- GA4/GSCの実利用・再訪・外部クリック・収益は秘密値や外部管理画面を開かず確認できないため、事業トラクションは未確認。コード量の多さを需要の証拠にはしない。

### P5 完了（2026-08-21 03:46 JST）
最終レポートを `plan/EXTERNAL_REVIEW_FINDINGS_2026-08-21.md` に作成した。指定の4部構成、重大度順の15指摘、各指摘の場所・現象・コード引用・実害・最小修正・確信度を確認し、`git diff --check` も成功した。

- ソースコード、設定、workflowは変更していない。
- 秘密ファイル・秘密値は開いていない。
- 禁止スクリプト、外部POST、デプロイ、git commit/push/branch操作は行っていない。
- 開始時から存在した `frontend/package-lock.json` のユーザー変更はそのまま保持した。

---

## FINDINGS_SO_FAR（途中で見つけた重要事項。消えないようにここへ都度追記）

<!-- 形式は指示書 §9 に準拠。中断してもここに残っていれば次回引き継げます。
例:
- [高] oriental/ml/postprocess.py:276 — 7日前スロット欠損時に純ML素通しになるが、その事実がスコアに記録されない
  根拠: `if base is None: out.append(q); continue`
  確信度: 高
-->

- [高・P1観測] `/store/shibuya` — 同じ店舗詳細内で予測情報が相互に矛盾して見える。確認時、上部は「店内の目安14名・8分前更新」、予測ハイライトは「ピーク目安22:15（男性31名/女性67名）」「予測更新 --:--」、本文は「21時半時点で約65名」「23時15分ごろがピーク」、さらに料金欄は「今夜の予測が出たら表示」と表示された。各表示の基準時刻・データ世代の説明がなく、どれを信じるべきか判断できない。確信度: 高（公開画面で実見）。
- [高・P1観測] `/reports` — 各Dailyカードは `2026-08-20 · 21:30便` と表示する一方、同じカード右下に `07/02 22:55` や `05/11 21:08` 等の古い日付が説明なしで併記された。カードを開くと本文は `2026-08-20 / 8月20日 21:35 更新` で現行だった。右下日付の意味が利用者には分からず、レポートが古いように見える。確信度: 高（公開画面で実見）。
- [中・P1観測] `/compare` — 3店舗の人数比較は一目で分かるが、カードに更新時刻がなく、店舗詳細の値と同時点か判断できない。混雑推移グラフの横軸が `20:40 / 05:00 / 13:20 / 21:40 / 04:45` と連続表示され、対象期間・日付境界が読み取れなかった。確信度: 高（公開画面で実見）。
- [中・P1観測] `/` — DOM読込直後の画面キャプチャではヘッダー以外がほぼ黒く、約2.5秒後にヒーローが表示された。アニメーションまたは描画待ちと推測するが原因はP1では未確認。初見離脱につながる長さかは実機未確認。確信度: 中。
- [低・P1観測] `/` — 「トップでは『直前に見た店』の推移だけを表示し、特定店の抜粋一覧は出しません（一覧と役割が重なるため）」は、利用者向け価値説明より内部の画面設計理由に見え、トップの訴求を弱める。確信度: 高（公開画面で実見）。
- [高・P2文書] `CLAUDE.md:105` と `README.md:44` / `plan/INDEX.md:90` / `plan/CODEx_PROMPTS.md:64-66` / `plan/ARCHITECTURE.md:175` — `/api/range` の公開契約が矛盾する。最新を自称する `CLAUDE.md` は日付粒度の任意 `from`/`to` を許可するが、他の「契約」「絶対不変」文書は追加禁止と断言する。誤った保守判断に直結するため、P3でコードとテストを確認する。確信度: 高（文書の矛盾自体）。
- [中・P2文書] `CLAUDE.md:60-63` と `plan/ARCHITECTURE.md:88` — Daily生成失敗時について、前者は公開済み良品を保持するcarry-over方式、後者は本文空・非公開・errorありと説明する。障害時にサイトが何を表示するかという重要な運用契約が一致していない。P3で実装確認予定。確信度: 高（文書の矛盾自体）。
- [中・P2構造] `app/page.tsx:41` / `app/api/forecast/route.ts:5` / ルート `tailwind.config.js` — 現役の `frontend/` とは別に、長崎固定・localhost固定の2025年旧Next.jsプロトタイプがルート直下に追跡されたまま残る。入口文書に説明がなく参照元も見つからず、初見では現役実装と誤認しやすい。確信度: 高（git履歴と参照検索で確認）。
- [低・P2文書] `plan/README.md:18,23` — 推奨読了順に `ARCHITECTURE.md` が3番と7番で重複し、ルートREADME・CODEx_PROMPTSにも別の読了順がある。`CLAUDE.md` は「3分マップ」を名乗るが情報量が多く、実測では関連入口文書を含め全体像の把握に相応の時間を要した。確信度: 高。
- [高・P3] `scripts/snapshot_forecasts.py:250-289` / `scripts/score_forecasts.py:647-680,972-978` — snapshot は期待42店との一致を検証せず、空・部分 `by_slug` を当夜の正規パスへ上書きしてから、空の場合だけ失敗終了する。翌朝の score は保存済み `by_slug` の件数を期待数にするため、空なら `expected=0` でcoverage失敗が無効、部分なら欠落店を分母から消して成功できる。`docs/FAILURE_MAP.md:25,150` には空snapshotが30日超続いて手動発見された実績がある。確信度: 高。
- [高・P3] `frontend/src/lib/supabase/blogDrafts.ts:363-402` / `frontend/src/app/reports/reports-client.tsx:377-386` / `supabase/migrations/20260329000000_blog_drafts_updated_at.sql:1-16` — 一覧だけが固定行を `created_at.desc` で選び、初回作成日時を表示する。`created_at` は更新しても不変なので、P1の「2026-08-20便」と「05/11・07/02」の併記を完全に説明する。50件取得後の重複除去も、42店×2便を覆わず、最新成功便の欠落・古いcarry-over便の選択が起こり得る。確信度: 高。
- [高・P3] `frontend/src/components/store/LatestForecastSummaryCard.tsx:19-58` / `frontend/src/app/hooks/useStorePreviewData.ts:439-466` / `frontend/src/components/PreviewMainSection.tsx:129-132` — 「予測ハイライト」は `forecastStatus` を見ず、予測不能時も実測から組み立てたピークと未設定値 `--:--` を予測として表示する。料金欄だけは `forecastStatus === "ok"` を要求するため、P1の「ピークあり・予測更新--:--・予測が出たら表示」の同居が起きる。確信度: 高。
- [高・P3] `frontend/src/app/compare/compare-client.tsx:254-276` / `frontend/src/app/compare/CompareChart.tsx:165-195` / `multi_collect.py:445-456` — 比較実測は各店舗固有の秒・マイクロ秒timestampを完全一致で全店の和集合へ置くが、線は `connectNulls=false` / `dot=false`。店舗間で時刻が一致しないため、自店点の間に他店だけの空行が入り、実測線が分断・不可視になり得る。確信度: 高。
- [中・P3] `frontend/src/app/compare/compare-client.tsx:177-229` / `frontend/src/app/compare/CompareChart.tsx:112-119` — 比較は日付・夜窓を指定せず最新200件を全点描画し、横軸は日付を捨てて `HH:MM` のみ。P1の `20:40 / 05:00 / 13:20 / 21:40 / 04:45` は複数夜と日中の混在。最新行の `ts` もカードから捨てるため鮮度を出せない。確信度: 高。
- [高・P3] `oriental/routes/tasks.py:37-56,137-198` / `multi_collect.py:426-484,1320-1377` / `Procfile:15-28` — 収集の既定経路は202を返した後のプロセス内daemon thread。Gunicorn再起動で途中消失でき、`collect_all_once()` が全店失敗を戻り値で返しても状態は `completed`、Supabase未設定はINSERT成功として数える。同期例外もHTTP 200の `ok:false`。cronが成功と誤認する経路が重なっている。確信度: 高。
- [高・P3] `scripts/local_report_job.py:653-723` / `scripts/monitor/check_daily_published.py:85-135` / `scripts/monitor/check_weekly_published.py:89-131` — 日次生成は生成失敗・書込失敗があっても常にexit 0。外部監視も日次は各便30/42店以上なら成功、週次は38店以上かつ全体の最新1件だけが8日以内なら成功するため、特定店舗の連続失敗・古い記事を正常扱いできる。確信度: 高。
- [高・P3] `oriental/routes/data_range.py:260-353` / `oriental/config.py:59-63` / `frontend/src/app/api/range_multi/route.ts:7-14` — Next側には30回のrate limitがあるが、公開RenderのFlask本体には認証・rate limitがなく直アクセスできる。全42店×最大6000行を最大12並列で取得でき、1500行超はキャッシュもしないため、通常利用者と同じ小さなRender/Supabase資源を外部から消費できる。公開GETでFlaskへ直接到達することも確認済み。確信度: 高。
- [高・P3] `oriental/ml/forecast_service.py:160-172` / `scripts/snapshot_forecasts.py:250-266` / `scripts/score_forecasts.py:398-438,734-765` — 配信前に純ML値は既存weightでbaselineとブレンドされ、その配信値だけをsnapshot保存する。翌朝はそのMAEを `ml` として次weight算出へ再投入するため、純ML成分の性能を評価できない自己参照ループになっている。反例（純ML20・baseline0・実測10・旧weight0.5なら配信誤差0→ML誤差0扱い→weight上昇→次配信悪化）が成立する。確信度: 高（実データでの悪化量は未確認）。
- [中・P3] `frontend/src/lib/supabase/blogDrafts.ts:77-103` / `frontend/src/app/api/reports/list/route.ts:15-25` — Supabase未設定、HTTP失敗、非配列、ネットワーク例外をすべて `null`/`[]` へ潰し、APIは `ok:true,data:[]`。障害時に利用者は「レポートがまだありません」と案内され、障害が観測不能になる。確信度: 高。
- [中・P3] `frontend/src/components/ui/FadeIn.tsx:21-38` / `frontend/src/components/home/HomeHero.tsx:8-31` — ファーストビュー全体をSSR時 `opacity:0` にし、hydration後のアニメーションで初めて表示する。P1の約2.5秒の黒画面を説明し、JS遅延/無効時は主要訴求が見えない。確信度: 高。
- [中・P3] `scripts/train_ml_model.py:1074-1115` — challengerは今回の最新test区間、championは以前のmetadataに保存された当時のtest MAEを比較しており、同じ実測区間で対戦していない。安全gateが期間難易度の差をモデル差と誤認し得る。確信度: 高（実際の誤判定履歴は未確認）。
- [中・P3] `scripts/generate_weekly_insights.py:1568-1570,507-511` — 水曜06:30 JST実行時もUTC日付を `target_date` に保存するため、火曜の日付で週報が公開される。確信度: 高。
- [中・P3文書確定] `oriental/routes/data_range.py:373-413` と `tests/test_range_params.py:44-80` により、`/api/range` の `from/to` は現役の明示契約だと確認。従って `README.md:44` / `plan/INDEX.md:90` / `plan/CODEx_PROMPTS.md:64-66` / `plan/ARCHITECTURE.md:175-176` の「追加禁止」が古く、最新の `CLAUDE.md:105-108` だけが実装と一致する。確信度: 高。
- [高・P4運用] `docs/FAILURE_MAP.md:19-25,133-169` / `docs/LOCAL_LLM_SETUP.md:18-24,93-117` — オーナーPC上の6タスクとローカルLLMが主経路で、GHA日次・週次cronは二重書込防止のため無効。PC停止10日、snapshot空30日超、通知メール未読という実績があり、複数の安全網は存在しても「異常が1人に必ず届く」運用になっていない。確信度: 高（現在のTask Scheduler principalと外部サービス通知設定は未確認）。
- [中・P4文書] `plan/ROADMAP.md:2,13-21` / `plan/STATUS.md:2-8` — ROADMAPは2026-03のGHA生成経路を実装済みとして残し、STATUSは2026-05で更新停止した旨を冒頭警告に追記している。最新の正本をCLAUDE.mdへ退避しているため誤読は軽減されるが、個人オーナーが障害時に見る入口が複数世代へ分散している。確信度: 高。
- [中・P4事業] 公開サイトと公式・競合の現行提供内容を比較すると、男女別リアルタイム人数は既に公式サイト/アプリと複数の横断サービスが提供している。MEGRIBIの継続理由は「人数を載せること」ではなく、42店横断の来店時刻判断を予測精度・鮮度・一貫した根拠付きで解決できる場合に限られる。確信度: 高（需要・継続利用率・収益性は未確認）。

---

## OPEN_QUESTIONS（オーナーにしか答えられない疑問。ここに溜めておく）

<!-- 例: Supabase の Storage バケット ml-models は Private か？（画面でしか確認できない） -->

- UptimeRobot、cron-job.org、Vercel/Render、`OPS_NOTIFY_WEBHOOK_URL` の通知先が現在どこまで有効か（秘密値・外部設定を開かず未確認）。
- Windows Task Scheduler 6本の現在のprincipalと「ログオン状態に関係なく実行」の実設定（リポジトリ外のため未確認）。

---

## NOTES（次の自分への申し送り。詰まった点・調査中の仮説など）

- P1では指示どおりリポジトリのコード・設計文書を未読。公開画面のGETとローカルなUI操作のみ実施し、外部送信・お気に入り追加・履歴削除はしていない。
- P2開始時は必ず `CLAUDE.md`、次に `plan/README.md` を読む。
- P2物理地図: 本番UI=`frontend/src`、Flask=`oriental`、収集=`multi_collect.py`、定時処理=`scripts`、CI/定時=`.github/workflows`、DB変更=`supabase/migrations`、テスト=`tests` + `frontend/src/**/*.test.*` + `frontend/e2e`。
- 個人運用としては、コード量そのものより「cron-job.org + Render + Vercel + Supabase + オーナーPC Task Scheduler/Ollama + GHA 21本 + LINE + X」という運用面の接点数が大きい。
- 作業開始時から `frontend/package-lock.json` にユーザー所有の変更がある。触らず保持する。レビューが変更するのは許可された進捗/最終レポートのみ。

---

## 【完了】2026-08-21 修正の出荷（第1〜2ラウンドの指摘のうち12件）

検証で CONFIRMED / PARTIAL と判定した12件を4班（担当ファイル分離）で修正し、main へ出荷済み。

| コミット | 内容 |
|---|---|
| `fix(frontend)` | F5 予測不在時の「予測ハイライト」偽装 / F6 一覧の並び(created_at→target_date) / F11 取得失敗を0件と偽らない(503+失敗カード) / F13 トップSSRのopacity:0 |
| `fix(compare)` | F7 収集時刻ズレで実測線が繋がらない(5分スロット丸め) / F10 夜窓1本に限定・時刻比例軸 |
| `fix(data)` | F1 壊れたsnapshotの昇格ガード / F3 収集の途中死の回収 / F8 監視の全店必須化 / F14 週報target_dateのJST化 |
| `fix(backend/docs)` | F4 `/api/*` レート制限＋`/api/range` 総行数上限 / F15 入口文書5本の契約分裂を是正 |
| `docs(review)` | CLAUDE.md §3 に契約を反映 / 監視の逃がし弁をGHA入力に追加 |
| `fix(sec)` ×2 | レート制限自体の穴（XFF先頭は詐称可 → 末尾へ）と、**本番で全く効いていなかった件**（Cloudflare配下のため CF-Connecting-IP を使用）＋ `/healthz` に計器追加 |

### 本番での実測（推測でなく計測して確認したこと）

- `/api/range_multi?stores=40&limit=1000` → **422 range-request-too-large**（40000行 > 12000）
- `/api/meta` を8並列で400連打 → 修正前 **429が0件**（＝効いていなかった）／修正後 **300通過・100を429**
- `/healthz` の `api_rate_limit` → `{enabled:true, per_min:300, tracked_keys:2, max_count_in_window:300}`
- `/store/sapporo_ag`（閉店）→ 410、`/compare` に `8/20(木) 19:00 → 翌05:00` 表示、
  `/store/shibuya` の見出しが「この夜の**実測**ハイライト」に

### 見送り（オーナーに報告済み・意図的）

- F9 予測の自己参照 blend（shadow採点）／F12 Champion/Challenger の評価期間
- Codex の新機能15案すべて（オーナー判断 2026-08-21）

### オーナー側で残っている判断

1. Supabase Storage bucket `ml-models` が Private か（1分で確認できる）
2. `CONTACT_FORM_URL` に入れる Google フォームの URL
3. 監視3案（LINE通知の集約 / PC死活 / 週次ダイジェストに運用行）— GitHub Secrets に
   `LINE_CHANNEL_ACCESS_TOKEN` / `LINE_USER_ID` が要る
4. 監視が厳しくなった件（全42店必須）でうるさければ `ALLOWED_MISSING_SLUGS` / `STRICT_ALL_STORES=0`

---

## 第3ラウンド（出荷した12件の修正の検証）

R3_STATUS: COMPLETE
R3_UPDATED: 2026-08-21 14:51 JST
R3_NEXT: なし（最終レポート `plan/EXTERNAL_REVIEW_ROUND3_FINDINGS.md` を確認待ち）
R3_DONE: `plan/EXTERNAL_REVIEW_ROUND3_2026-08-21.md` を最初から最後まで全文読了／12件を現行コード・公開本番GET・raw SSR・ハイドレーション後DOM・公開GitHub Actions履歴・一次資料で検証／V1〜V10へ回答／テスト経路と本番経路の差を棚卸し／指定4部構成の最終レポートを作成／`git diff --check` 成功
R3_FINDINGS: FIXED 3件（F5/F6/F13）、PARTIAL 8件（F1/F4/F7/F8/F10/F11/F14/F15）、NOT FIXED 1件（F3）、REGRESSION 0件。F3は文書化された既定async経路が完了結果を返さない。F4はGunicorn worker再生成でrate bucketが消える。F1/F8/F14は修正後の本番定期実行がまだ0回。F10は19時切替時に旧fetchが新夜stateを再上書きできる。F11はstore-summaryの503を店舗画面が捨て、F15は現役API_CONTRACTに逆の契約が残る。F7は通常本番では線が繋がるが、5分超遅延/bucket境界では同症状が残るため依頼書の定義どおりPARTIAL。

依頼書: `plan/EXTERNAL_REVIEW_ROUND3_2026-08-21.md`
最終レポートの出力先: `plan/EXTERNAL_REVIEW_ROUND3_FINDINGS.md`
