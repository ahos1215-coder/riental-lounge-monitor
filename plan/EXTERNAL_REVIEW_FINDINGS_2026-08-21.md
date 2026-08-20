# 外部レビュー結果（2026-08-21）

レビュー対象: MEGRIBI（めぐりび）公開サイトと本リポジトリ  
前提: 非エンジニアのオーナー1人がAIを使って開発・運用している

## 第1部: 率直な総評

### 一言で言うと

**来店直前の「今どこへ、何時に行くか」という良い問いに答えるプロダクトだが、利用者が最も信じたい予測と、運用者が最も信じたい正常判定の両方に、まだ“緑なのに欠けている”経路がある。**

サイトの目的は明快で、店舗詳細は実用的です。しかし、その中核価値を支えるために、記事生成、複数世代の予測、ローカルLLM、個人PCの定時タスク、21本のGitHub Actionsなどが積み上がり、個人開発としての安全限界を越えています。次に必要なのは機能ではなく、機能を減らして「表示された値は同じ夜・同じデータ世代で、42店舗全部が揃っている」と証明することです。

### 良いと思った点

1. **解く問題と画面の基本導線がよい。** 数秒で「相席ラウンジの現在人数と今夜の混雑予測」だと理解できました。店舗詳細の男女別人数、更新からの経過時間、実測/予測グラフ、料金試算は来店判断に直結しています。確認したスマホ幅でも主要操作に支障はありませんでした。
2. **事故を学習してテストへ落とす文化がある。** JSTの夜境界、月・年またぎ、carry-over、キャッシュ、監視などのテストは細かく、FrontendのVitest 746件と実行可能だったPython 91件はすべて通りました。日時の純粋関数化も堅実です。
3. **失敗履歴を隠していない。** `docs/FAILURE_MAP.md` は、PC停止10日や空snapshot 30日超など、都合の悪い実績まで具体的に残しています。この率直さは、仕組みを小さく立て直すうえで大きな強みです。

### 悪い・危ういと思った点

1. **中核表示の意味が揃っていない。** 実測由来のピークを予測として出すカード、別パイプラインの記事、予測が無いという料金欄が同じ店舗画面に同居します。正しい数値であっても、出所と世代が違えば利用者には矛盾です。
2. **「成功」の定義が弱い。** 42店舗の一部しかないsnapshot、保存先未設定、日次記事の部分失敗などを、複数の経路が成功扱いできます。テストは個々の事故をよく覆っていますが、「期待する42店舗が、同じ夜について、最後まで保存・表示されたか」というend-to-endの契約がありません。
3. **個人運用として枝が多すぎる。** Windows Task Scheduler、Ollama/GPU排他、GitHub Actions、cron-job.org、Render、Vercel、Supabase、複数通知経路を1人で把握するのは現実的ではありません。監視があっても、通知が読まれず10日・30日単位で止まった実績が、この構成の限界を示しています。

### 5段階評価

| 観点 | 評価 | 理由 |
|---|---:|---|
| プロダクト | **3 / 5** | 課題と利用場面は明快で、スマホUIにも実用性がある。一方、中核の予測表示が矛盾し、実際の再訪・送客・収益は未確認。 |
| コード | **3 / 5** | 境界テスト、共有日時ロジック、障害別の回帰テストは強い。しかし、部分成功、非同期ジョブ、予測の自己参照学習など、経路全体の意味に重大な穴がある。 |
| 運用 | **2 / 5** | 手順書と監視は多いが、単一PC依存と通知の沈黙死が実害化している。現状の広さを非エンジニア1人で長期維持するのは難しい。 |

## 第2部: 利用者としての感想（P1）

この部は、コードを読む前に公開サイトをPC幅とスマホ幅で操作したときの印象です。公開画面の確認にはブラウザ操作を使い、リポジトリの知識を混ぜずに記録しました。

### 最初の数秒

- 「全国の相席ラウンジについて、今の男女別人数とAI予測を見て、行く店と時刻を決めるサイト」だと数秒で理解できました。
- 想定利用者は、今夜相席店へ行く候補を比較している人です。検索、一覧、店舗詳細への導線は素直でした。
- 毎日眺めるメディアというより、外出直前に検索やお気に入りから再訪する道具に見えました。この狭い用途は弱みではなく、むしろプロダクトの焦点になり得ます。

### 使ってよかった点

- 店舗詳細で「何分前の情報か」が見え、男性・女性を分けて確認できるのは有用でした。
- 実測と予測の推移、料金試算、住所・店舗情報まで同じ画面で見られ、来店前の判断を一画面で終えられます。
- 約390×844のスマホ幅では、ハンバーガーメニュー、店舗検索、カード、詳細グラフを操作でき、横にはみ出す箇所も見つかりませんでした。

### 信用を失った点

- `/store/shibuya` では、確認時の実測は「店内の目安14名・8分前更新」でしたが、同じ画面に「ピーク目安22:15（男性31名/女性67名）」「予測更新 --:--」、記事本文には「21時半時点で約65名」「23時15分ごろがピーク」、料金欄には「今夜の予測が出たら表示」が同居しました。どれを信じるべきか判断できませんでした。
- `/reports` のカードは `2026-08-20 · 21:30便` としながら、右下に説明なく `05/11` や `07/02` を表示しました。本文は8月20日版だったため、古い記事なのか更新日時なのか分かりませんでした。
- `/compare` は3店舗の現在人数を見比べやすい一方、カードに更新時刻がなく、グラフの横軸が `20:40 / 05:00 / 13:20 / 21:40 / 04:45` と続きました。どの夜の比較か読み取れませんでした。
- トップは初回描画でヘッダー以外がほぼ黒く、約2.5秒後にヒーローが現れました。初見でサイトが空に見える時間としては長いです。
- 「トップでは特定店の抜粋一覧は出しません（一覧と役割が重なるため）」という文言は、利用者への価値説明ではなく内部設計の説明に見えました。

### また使うか

今夜の店選びをしているなら再利用したいです。ただし、現状では人数の鮮度は信じても、予測時刻や記事は補助情報としてしか信じません。再訪を増やす最短経路は記事を増やすことではなく、同じ画面の数値が同じデータ世代を指していると分かることです。

## 第3部: 具体的な指摘（P2・P3）

### 検証範囲

- `tsc --noEmit`: 成功。
- Vitest: **48ファイル、746テストすべて成功**。
- 依存追加なしで実行できたPythonテスト: 日次carry-over・収集heartbeat 57件、blend weight・score summary・公開監視 34件、**計91件すべて成功**。
- `python -m pytest -q` 全体は、このPCにLightGBM / SciPyが無く、収集時24エラーで実行不能でした。依存を追加していないため、全Pythonテスト成功とは評価していません。
- 禁止されたsnapshot/scoreスクリプト、argparseのないスクリプト、publishモードは実行していません。秘密ファイル・秘密値も開いていません。

重大度「致命的」に該当する、直ちに秘密漏えいまたは不可逆な全データ消失を起こす箇所は確認できませんでした。以下は実害の大きい順です。

### [重大度: 高] 空・部分snapshotが正規ファイルを上書きし、翌朝の採点が正常終了できる

- 場所: `scripts/snapshot_forecasts.py:250-289`、`scripts/score_forecasts.py:647-680`、`docs/FAILURE_MAP.md:23-25`
- 現象: 予測APIが全滅または一部店舗だけ失敗すると、成功した店舗だけの `by_slug` を同夜の正規パスへ保存します。空の場合も保存後に終了コード1、部分欠落なら終了コード0です。翌朝は保存済み件数を期待数にするため、空ではcoverage検査が無効、部分欠落では欠けた店舗が分母から消えます。
- 根拠:

```python
path = f"accuracy/snapshots/{night_date}.json"
_storage_put(bucket, path, json.dumps(payload, ensure_ascii=False).encode("utf-8"), supabase_url, key)
print(f"[snapshot] saved {len(by_slug)}/{len(slugs)} stores (v2 for {v2_ok}) -> {bucket}/{path}")
if not by_slug:
```

  `score_forecasts.py:679-680` は `by_slug = snapshot.get("by_slug") or {}`、`expected = len(by_slug)` としています。失敗履歴には空snapshotが30日超続いた実績があります。
- 実害: 良品snapshotを欠測ファイルで上書きし、精度検証・blend更新が不完全でもGitHub Actionsを緑にできます。予測改善の判断材料が静かに欠落します。
- 修正案: 期待slug集合と完全一致することをPUT前に検証し、空・部分時は正規ファイルを更新しない。payloadへ `expected_slugs` / `missing_slugs` を保存し、score側も現行の全店舗集合を分母にする。
- 確信度: 高。コード経路と過去の空snapshot実績を確認。禁止スクリプトの本番実行はしていません。

### [重大度: 高] 収集をdaemon threadへ渡した時点で202を返し、途中終了を回収できない

- 場所: `oriental/routes/tasks.py:137-198`、`Procfile:15-28`
- 現象: 既定の収集はHTTP 202を先に返し、同じGunicornプロセス内のdaemon threadで継続します。その後にワーカーの定期recycle、デプロイ、クラッシュが起きると、cronは受理成功を見たまま収集だけが途中で消えます。状態と排他もプロセス内です。
- 根拠:

```python
logger.info("collect_all_once.start mode=async task_id=%s", task_id)
t = threading.Thread(target=_run_collect_background, args=(task_id,), daemon=True)
t.start()

return jsonify({
```

  `tasks.py:198` で202を返し、`Procfile:28` は `--max-requests 1500 --max-requests-jitter 200` でワーカーを定期再生成します。
- 実害: 一部店舗だけ書いた状態でも起動元は成功と認識し、最新人数と学習履歴が店舗ごとに欠けます。再起動後はタスク状態も失われます。
- 修正案: 当面は同期実行にして、完了結果をHTTPステータスへ反映する。長期的には永続ジョブキューへ移し、ジョブ状態・排他・再試行をプロセス外へ置く。
- 確信度: 高（設計上の消失可能性）。本番ワーカー停止による再現はしていません。

### [重大度: 高] 永続化できていなくても収集タスクを成功扱いできる

- 場所: `oriental/routes/tasks.py:37-56,154-166`、`multi_collect.py:426-443,1027-1031,1126-1130`
- 現象: `collect_all_once()` が失敗件数を戻り値に含めても、例外でなければbackground状態は無条件で `completed` です。同期経路も戻り値を検査せず `ok:true`。さらにSupabase未設定時のINSERTは成功を返します。
- 根拠:

```python
if not HAS_SUPABASE:
    return True
```

  `tasks.py:41-47` は結果の成功/失敗件数を判定せず `status="completed"` と記録します。
- 実害: 設定漏れや全店舗失敗でもデータを1件も保存せず緑になり、サイト停止は後段の鮮度監視まで見つかりません。
- 修正案: 本番モードは必須設定を開始時にfail-fastし、dry-runを別モードにする。期待店舗数、取得成功数、保存成功数が一致した場合だけ成功とし、同期HTTP・非同期状態の両方へ反映する。
- 確信度: 高。静的に確定。実環境の設定値は見ていません。

### [重大度: 高] 高コストな公開Backend APIはNext.js側のレート制限を直接迂回できる

- 場所: `oriental/routes/data_range.py:260-353`、`oriental/config.py:59-63`、`frontend/src/app/api/range_multi/route.ts:7-14`
- 現象: Next.jsプロキシには30回のrate limitがありますが、公開Render URLのFlask `/api/range_multi` 自体には認証・rate limitがありません。全店舗、1店舗最大6000行、最大12並列の問い合わせを直接実行できます。1500行超はキャッシュ対象外です。
- 根拠:

```python
with ThreadPoolExecutor(max_workers=min(12, len(slugs))) as pool:
    futures = [pool.submit(_fetch_slug, s) for s in slugs]
    for fut in as_completed(futures):
        slug_key, data, cache_status = fut.result()
```

  副作用のない未知storeへのGETで公開Flaskへ直接到達し、`unknown-store` の404を返すことを確認しました。負荷試験はしていません。
- 実害: 1リクエストで多数のSupabase読取と大きなJSON生成を強制でき、小規模Renderワーカーと通常利用者の応答を圧迫します。
- 修正案: Flask側でIP/トークン単位のrate limitを適用し、店舗数と総返却行数にも低い上限を置く。Next.jsだけに防御を置かない。
- 確信度: 高（迂回経路と処理上限）。実際の枯渇量は未確認。

### [重大度: 高] 予測取得不能でも実測ピークを「予測ハイライト」と表示する

- 場所: `frontend/src/components/store/LatestForecastSummaryCard.tsx:19-58`、`frontend/src/app/hooks/useStorePreviewData.ts:439-466`、`frontend/src/components/PreviewMainSection.tsx:129-132`
- 現象: 予測が空で再試行を終えると `forecastStatus` だけを `unavailable` にし、既存snapshotのピーク値は保持します。要約カードはstatusを見ずにそのピークを予測として表示し、`--:--` も有効な更新時刻として受け入れます。料金欄だけはstatusが `ok` かを確認します。
- 根拠:

```tsx
const peak = Math.max(0, Math.round(Number(snapshot.peakTotal ?? 0)));
const peakTime = snapshot.peakTimeLabel?.trim() || "";
const updated = snapshot.forecastUpdatedLabel?.trim() || "";
```

  この関数内には `forecastStatus` 判定がなく、`LatestForecastSummaryCard.tsx:48-49` は `--:--` を除外しません。
- 実害: P1で実見した「ピーク予測あり」「予測更新 --:--」「今夜の予測が出たら表示」の同居が起きます。利用者が実測ピークを将来予測だと誤認します。
- 修正案: `forecastStatus !== "ok"` なら予測チップを一切出さない。ピークは予測seriesだけから算出し、`--:--` などのplaceholderを未設定値として扱う。
- 確信度: 高。公開画面の現象とコードが一致。

### [重大度: 高] レポート一覧が更新日時でなく初回作成日時を選び、表示する

- 場所: `frontend/src/lib/supabase/blogDrafts.ts:355-402`、`frontend/src/app/reports/reports-client.tsx:377-386`、`scripts/local_report_job.py:300-315`、`supabase/migrations/20260329000000_blog_drafts_updated_at.sql:1-16`
- 現象: 日次レポートは店舗・便ごとの固定 `facts_id` をPATCH更新するため、`target_date` と `updated_at` は進みますが `created_at` は初回作成日のままです。一覧は `created_at.desc` の50件を取得して店舗ごとに先勝ちし、その古い日時をカードにも表示します。
- 根拠:

```ts
`${endpoint}?select=store_slug,target_date,edition,created_at,mdx_content` +
`&content_type=eq.${encodeURIComponent(contentType)}` +
`&is_published=eq.true&error_message=is.null&mdx_content=not.eq.` +
`&order=created_at.desc&limit=${Math.min(limit, 200)}`;
```

  migration自身も「created_at stays at original INSERT time」と明記しています。
- 実害: P1の「2026-08-20便」と「05/11・07/02」の併記を生みます。42店×2便の固定行に対して取得上限50なので、最新成功便の店舗が一覧から漏れたり、古いcarry-over行が選ばれたりもします。
- 修正案: `updated_at` を取得し、`target_date.desc,updated_at.desc,created_at.desc` で選択・表示する。重複除去前に期待する全固定行を取得できる上限へ変更する。
- 確信度: 高。公開画面、保存方式、migrationが一致。

### [重大度: 高] 比較グラフは店舗ごとの時刻差で実測線を分断する

- 場所: `frontend/src/app/compare/compare-client.tsx:254-276`、`frontend/src/app/compare/CompareChart.tsx:165-195`、`multi_collect.py:445-456`
- 現象: 収集時刻は店舗ごとに `datetime.now()` で採番され、秒・マイクロ秒が一致しません。比較側は全店舗timestampの和集合を作り、完全一致した点だけ各系列へ入れます。系列は `connectNulls=false` かつ `dot=false` です。
- 根拠:

```tsx
const actual = data.sparkline.find((p) => p.ts === ts);
const fc = data.forecast.find((p) => p.ts === ts);
if (actual) point[`actual_${slug}`] = actual.total;
if (fc) point[`forecast_${slug}`] = fc.total;
```

  `CompareChart.tsx:180-182` は点を非表示にしてnullを接続せず、収集側 `multi_collect.py:446-451` は各書込時に現在時刻を生成します。
- 実害: 自店の2点の間に他店舗だけの行が入り、実測線が短く分断されるか見えなくなります。比較という中核機能のグラフが実データを正しく伝えません。
- 修正案: 収集または描画前に共通の5分slotへ丸めて結合する。真の長時間欠測だけを切り、それ以外の店舗間の空行は接続する。
- 確信度: 高。時刻生成と描画条件から決定的。

### [重大度: 高] 日次・週次の部分店舗障害をジョブと監視の両方が正常扱いできる

- 場所: `scripts/local_report_job.py:653-723`、`scripts/monitor/check_daily_published.py:85-135`、`scripts/monitor/check_weekly_published.py:89-131`
- 現象: 日次publishは生成失敗・書込失敗数を表示しても常にexit 0です。日次監視は各便30件以上、週次監視はdistinct店舗数と全体の最新1件だけを見ます。たとえば42店中12店が毎日失敗しても日次は緑、週次は41店が古く1店だけ新しくても緑になれます。
- 根拠:

```python
if args.mode == "dry-run":
    _pr("[info] mode=dry-run -> NOTHING was written to Supabase.")
return 0
```

  日次監視は `ok = n >= floor`、既定floorは30です。週次は全行で1つの `newest` を算出します。
- 実害: 特定店舗の利用者だけ古い記事を見続けても、Task SchedulerとGitHub監視の2本がともに正常になります。
- 修正案: active storesの期待slug集合との差分と、各slugの対象日・更新日時を検査する。publishは `write_err` / `gen_fail` があれば非ゼロにし、carry-overは別のdegraded状態として通知する。
- 確信度: 高。現在の外部通知先とTask Scheduler実設定は未確認。

### [重大度: 高] blend学習が「すでにblend済みの配信値」を純ML誤差として再投入する

- 場所: `oriental/ml/forecast_service.py:158-172`、`scripts/snapshot_forecasts.py:250-266`、`scripts/score_forecasts.py:398-438,734-765`
- 現象: 純ML予測は既存weightでbaselineとblendされた後に配信されます。snapshotはその配信後の `total_pred` だけを保存し、翌朝はその誤差を `live_mae`、さらにML誤差として次のweightへ使います。純ML成分の性能を評価できません。
- 根拠:

```python
w_ml_used = self._blend_weight_for(store_id)
data, blended_slots = blend_with_baseline(
    data, df, self.tz, w_ml=w_ml_used, freq_min=freq_min
)
```

  snapshotは `total_pred` しか残さず、score側はそれを `ml_err` に入れ、後で `entry.get("live_mae")` をML側の誤差として集計します。
- 実害: 実測10、純ML20、baseline 0、旧weight 0.5なら、配信10で誤差0となり「MLが良い」と誤認してweightを上げ、次回の配信を18へ悪化させる反例が成立します。
- 修正案: snapshotへ `raw_ml_pred`、`baseline_pred`、`served_pred`、使用weightを別々に保存し、同一slotの純MLとbaselineの残差でweightを評価する。当面は自動weight更新を止める。
- 確信度: 高（数学的な自己参照は確定）。実データ上の悪化量は未確認。

### [重大度: 中] 比較画面は夜窓を指定せず、複数日を時刻だけで表示する

- 場所: `frontend/src/app/compare/compare-client.tsx:177-229`、`frontend/src/app/compare/CompareChart.tsx:108-119`
- 現象: 比較画面は `from` / `to` や19:00–05:00の夜窓を付けず、最新200件と今夜の予測を同じ軸へ載せます。X軸は日付を捨てて `HH:MM` だけを表示し、カードでは最新行の `ts` も保持しません。
- 根拠:

```tsx
fetch(`/api/range_multi?stores=${csvSlugs}&limit=200`).then((r) => r.json()).catch(() => ({})),
SHOW_MEGRIBI_JUDGMENTS
  ? fetch(`/api/megribi_score?stores=${csvSlugs}`).then((r) => r.json()).catch(() => ({}))
  : Promise.resolve({}),
fetch(`/api/forecast_today_multi?stores=${csvSlugs}`).then((r) => r.json()).catch(() => ({})),
```

- 実害: P1で見た日中・翌朝・別夜が混在した時刻列になり、同時点の店舗比較か判断できません。
- 修正案: 店舗詳細と同じ夜基準日関数で `from` / `to` と夜窓を適用する。日付境界のtickには日付も表示し、各カードに最新実測時刻を出す。
- 確信度: 高。公開画面の軸とfetch条件が一致。

### [重大度: 中] レポート取得障害を「記事が0件」として正常応答する

- 場所: `frontend/src/lib/supabase/blogDrafts.ts:77-103`、`frontend/src/app/api/reports/list/route.ts:15-25`
- 現象: Supabase未設定、HTTPエラー、非配列JSON、ネットワーク例外をすべて `null` / `[]` へ変換し、APIは `ok:true, data:[]` を200で返します。
- 根拠:

```ts
if (!isBlogDraftsConfigured()) {
  return NextResponse.json(
    { ok: true, data: [] },
    { status: 200, headers: { "cache-control": CACHE_HEADER } },
```

- 実害: 障害時に利用者は「レポートがまだありません」と案内され、オーナーの外形監視も正常な空状態と障害を区別できません。
- 修正案: 設定/上流障害は5xxまたは `ok:false, degraded:true` で返す。必要ならlast-known-goodを明示的に表示し、空と障害を分ける。
- 確信度: 高。

### [重大度: 中] Champion/Challenger gateが同じ評価期間を比較していない

- 場所: `scripts/train_ml_model.py:1002-1018,1108-1115`
- 現象: challengerのMAEは今回の最新test区間、championのMAEは既存metadataに保存された以前のtest区間です。季節や繁閑が違うため、モデル差ではなく期間の難易度差をgateが比較します。
- 根拠:

```python
new_mae = (new_entry.get("overall") or {}).get("total_mae")
old_entry = existing_metrics.get(store_id)
old_entry = old_entry if isinstance(old_entry, dict) else None
old_mae = (old_entry.get("overall") or {}).get("total_mae") if old_entry else None
decision, reason = _gate_decision(new_mae, old_mae, cfg.gate_max_regression_pct)
```

- 実害: 良い新モデルを拒否して古いモデルを固定したり、悪い新モデルを通したりできます。20%閾値が安全網になりません。
- 修正案: 現行championも今回と同じ `test_df` へロードして採点し、同一行のpaired比較にする。できない間は自動昇格を止める。
- 確信度: 高（比較期間の不一致）。実際の誤昇格履歴は未確認。

### [重大度: 中] トップの主要訴求がSSR時点で透明になる

- 場所: `frontend/src/components/ui/FadeIn.tsx:21-38`、`frontend/src/components/home/HomeHero.tsx:8-31`
- 現象: Above-the-foldのヒーロー全体を `FadeIn` で包み、SSR HTMLの初期状態を `opacity:0` にします。hydrationとアニメーション開始まで主要内容が見えません。
- 根拠:

```tsx
<motion.div
  initial={{ opacity: 0, ...offset }}
  animate={{ opacity: 1, x: 0, y: 0 }}
  transition={{ duration, delay, ease: [0.25, 0.46, 0.45, 0.94] }}
```

- 実害: P1の約2.5秒の黒画面を説明します。低速端末では初見離脱、JavaScript無効時は主要訴求の恒久非表示につながります。
- 修正案: ヒーロー外枠は通常の可視HTMLまたは `initial={false}` にし、アニメーションは表示を阻害しない装飾だけに限定する。初回paintのE2E検査を追加する。
- 確信度: 高。公開画面と生成済みSSR HTMLでも確認。

### [重大度: 中] 水曜06:30 JSTの週報がUTC基準で火曜日付になる

- 場所: `scripts/generate_weekly_insights.py:507-511,1568-1570`
- 現象: 週報の定期実行は水曜06:30 JSTですが、その時刻は火曜21:30 UTCです。`target_date` にUTCの `now.date()` を使うため1日前の日付を保存します。
- 根拠:

```python
now = datetime.now(timezone.utc)
date_label = now.date().isoformat()
generated_at = _iso(now)
```

- 実害: 公開週報の日付・一覧順・監視対象日が利用者の暦とずれます。
- 修正案: `target_date` はJSTの現在日時から計算し、`generated_at` だけUTCで保存する。水曜06:30 JSTを固定した境界テストを追加する。
- 確信度: 高。

### [重大度: 中] 入口文書が現役API契約と運用経路について複数世代に分裂している

- 場所: `CLAUDE.md:101-108`、`README.md:43-46`、`plan/INDEX.md:88-91`、`plan/ROADMAP.md:1-21`、`plan/STATUS.md:1-8`、`oriental/routes/data_range.py:373-413`
- 現象: 現役コードと最新の `CLAUDE.md` は `/api/range` の任意 `from` / `to` を正式に受けますが、READMEとINDEXは「追加禁止」と断言します。ROADMAPはDaily/WeeklyをGHA定期生成と記載したまま、現行はローカルOllama主経路です。STATUSは更新停止を冒頭で警告していますが、古い本文が大半を占めます。
- 根拠:

```markdown
## 重要な制約（必ず守る）
- `/api/range` の引数は `store` / `limit` のみ（from/to などの追加は禁止）。
- 夜窓（19:00–05:00）の判定・絞り込みは **店舗 UI** とし、フロント（`useStorePreviewData.ts`）で行う。
```

  一方、`data_range.py:373-412` は `from` / `to` を解析し、テストもこの契約を固定しています。
- 実害: 障害対応時に正しい経路や変更禁止範囲を誤り、既存機能を「契約違反」として消す、または停止済みGHAを主経路だと思い込む可能性があります。
- 修正案: 入口を `CLAUDE.md` と1ページの運用Runbookだけにし、README/INDEX/ROADMAP/STATUSの現況説明を削除または自動生成リンクへ置き換える。契約はコードテストから生成できる範囲を増やす。
- 確信度: 高。

## 第4部: 事業性と方向性への意見（P4）

### 続ける価値はあるか

**条件付きで、あります。** ただし「相席業界の総合メディア」や「AI記事を大量生成する仕組み」としてではなく、**今夜の店選びに3分で答える小さな実用サービス**としてです。

リアルタイム人数そのものは独占的ではありません。レビュー時点で、[オリエンタルラウンジ公式](https://oriental-lounge.com/)は店舗別のリアルタイム男女人数を掲載し、[JIS公式アプリ](https://jis.bar/app/)も店舗のリアルタイム状況を訴求しています。[相席Now](https://aisekinow.com/)のような横断サービスもあります。したがって、MEGRIBIの差別化は「人数が見える」ことではなく、次の組み合わせです。

- 複数ブランド・複数店舗を同じ尺度で比べられること
- いまの値だけでなく、今夜この後のピークと入店時刻を示すこと
- その予測が新鮮で、欠測やfallbackを隠さず、過去実績で検証されていること

この3点が揃えば、公式サイトを店舗ごとに開くより便利です。逆に、予測の世代が画面内で食い違うなら、公式の現在人数だけを見る方が安全になってしまいます。

実際の需要については、GA4/GSCの利用者数、再訪率、`store_view` 後の行動、外部送客クリック、収益を確認していません。秘密値・外部管理画面を開かなかったためです。325コミットや多数の機能は開発量の証拠であって、需要の証拠ではありません。

### 個人で維持できる運用か

**現状のままでは難しいです。** `docs/FAILURE_MAP.md:19-25` には、GitHub失敗メールが読まれない、PC停止が10日発覚しない、空snapshotが30日超続く、という実績があります。`docs/LOCAL_LLM_SETUP.md:93-117` は日次・週次の主経路を対話ログオン可能な個人PCへ登録し、二重書込回避のためGHA定期実行を止めています。

これはオーナーの注意力の問題ではありません。1人が日常的に見るべき状態が多すぎます。監視をさらに増やすと、監視の失敗を監視する仕事も増えます。必要なのは監視の本数ではなく、次の一文を毎朝1か所で確認できることです。

> 昨夜分は期待42店舗中42店舗が収集・予測・snapshot・公開まで完了し、欠測0、最古データは許容時間内。

この一文が偽なら、必ずオーナーが普段読む通知先1つへ届く構成にします。

### 次の3ヶ月で「1つだけ」やること

**Trust / Reliability Reset（信頼性リセット）だけを行う。** 新機能ではなく、既存の中核を縮小して一つの完全性契約へ揃える3ヶ月です。

一つの取り組みとして、以下を同じ定義のもとで実施します。

1. 夜ごとの正規データに `night_date`、`generation_id`、`captured_at`、`expected_slugs`、`missing_slugs`、`source`、`raw/served` を持たせる。
2. 期待42店のどれか1店でも欠けたら「成功」にしない。良品を部分成果物で上書きしない。
3. 店舗カード・比較・記事は同じ世代を参照し、画面に「実測更新」「予測生成」「欠測/fallback」を短く明示する。
4. 1本のend-to-end canaryが、収集→予測→snapshot→表示を全店舗について検査する。
5. 通知先をオーナーが日常的に読む1つへ絞り、意図的な失敗を起こす通知訓練を月1回行う。

3ヶ月の完了条件は「コードを増やした」ではなく、少なくとも30夜連続で、部分欠落を正常扱いせず、通知訓練も届き、公開画面の予測世代が一致したことです。その後に、同期間の再訪利用と送客行動を見て継続判断します。

### 今すぐ止める・捨てるもの

- Daily 2便×42店とWeeklyの生成AI文章量産。現在人数と単純な定型要約だけで十分です。
- Editorial/X等の半自動メディア運用。中核の来店判断が安定するまで再開しない。
- v2 shadow、自己更新blend、複雑なChampion/Challenger自動昇格。raw/servedを分けた同一期間評価ができるまで固定baselineを使う。
- Web Push、課金、ブランド追加、SEO機能の追加。信頼性と実利用が証明されるまで保留する。
- 正本でない旧Next.jsプロトタイプ、古いSTATUS/ROADMAPの現況説明、重複した入口文書。履歴はGitに任せ、運用時に読む文書を減らす。

比較機能は捨てる必要はありませんが、時刻slotと夜窓を直すまではグラフを一時的に隠し、鮮度付きの現在値比較だけを出す方が誠実です。

### 90日後の判断

次の条件が揃えば続ける価値があります。

- 全期待店舗の鮮度と予測coverageを毎夜説明でき、欠測を緑にしない。
- 同じ夜・同じslotで単純baselineより予測が継続的に良い。良くない店舗は予測を出さない。
- GA4/GSC等で、店舗詳細の再訪または送客行動が実際にある。初期2週間を基準に、残り期間で改善している。

揃わなければ、AI予測・記事・自動化を閉じ、リアルタイム横断一覧だけを低コストで残す判断が妥当です。プロジェクト全体をやめるかどうかではなく、**利用者が使っている最小部分だけを残せるか**で判断してください。

## 未確認事項

- GA4/GSCの実トラフィック、再訪、検索流入、送客クリック、収益。
- UptimeRobot、cron-job.org、Render/Vercel、外部webhookの現在の通知先と有効状態。
- Windows Task Scheduler 6本の現在のprincipal、ログオン条件、直近実行結果。
- LightGBM/SciPyを含む完全なPythonテスト環境での全件結果。

これらは秘密ファイルや外部管理画面を開かないルールに従い、推測していません。
