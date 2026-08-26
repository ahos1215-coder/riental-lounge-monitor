# めぐりび 計測基盤レビュー 第2ラウンド findings

作成日: 2026-08-26  
対象: `plan/ANALYTICS_REPORT_TO_CODEX_2026-08-26.md` §8-1〜§8-4  
判定: **CONDITIONAL ACCEPT（方向は採用。ただし「クリーンな観測開始」の確定には追加修正・外部確認が必要）**

---

## 0. 結論

Claude の実装は、以前の状態から明確に改善しています。

- `searchParams` 変更を手動PVの発火条件から外したこと
- `?store=` の自動付与を店舗ページから削除したこと
- 実イベントの店舗識別子を `store_slug` に統一したこと
- `official_site_click` / `second_venue_click` を追加したこと
- 週報の総数取得失敗をゼロと区別したこと
- Claude / Codex 共通の read-only CLI と runbook を作ったこと

は、いずれも正しい方向です。これらを戻す理由はありません。

一方、現状を「2026-08-26から完全に信用できる計測が始まった」と扱うことには反対します。
主な理由は次の6点です。

1. **GA4管理画面の履歴イベントPVがOFFか未確認**で、ONならquery-only変更の水増しがコード外から続く。
2. GSCの「確定済み日」は、**公式仕様上メタデータが返らないリクエスト**から読もうとしており、実際は固定3日ルールの推定である。
3. 最新CLIの前期間比は、**速報を含む現在期間と確定済みの過去期間**を比較しており、標準コマンドのdeltaをそのまま施策判断に使えない。
4. `gsc.pages` だけ失敗した場合、週報・CLIともに派生指標の「有効クリック」が**偽の0**になる。
5. PV定義変更と `report_read` → `report_view` の境界を、CLI・週報が機械的に認識せず、境界越しの偽の増減を表示する。
6. Claude の実装報告書そのものが、**実測値と実検索語をGit追跡ファイルへ記載してpush済み**であり、同文書とrunbookの禁止事項に反している。

### 総合判定表

| 対象 | 判定 | 要点 |
|---|---|---|
| PVのpathnameガード | **PASS（条件付き）** | 純粋関数の判定は妥当。ただしGA4拡張計測OFFが成立条件で、実ブラウザの1回性は未検証 |
| 初回PVの二重送信反証 | **静的にはPASS** | 現行レンダー順ではeffect側がno-op、config側が初回を送る。ただしタイミング依存を残す |
| イベント名union | **PASS** | 10イベントを閉じたことは妥当 |
| イベントパラメータ型 | **FAIL** | index signatureにより旧キー・typo・必須欠落が全て通る |
| 送客クリック2種 | **PASS（小修正あり）** | 現行ブランド・リンクでは妥当。JIS将来誤分類と分析用ディメンション漏れあり |
| `last_confirmed_week()` | **PARTIAL** | 月曜定期経路は保守的で安全だが、API確定確認ではなく一週古いheuristic |
| 週報の失敗伝播 | **PARTIAL** | totalsは改善。派生指標、終了コード、canonical JSON昇格に穴が残る |
| 最新read-only CLI | **PARTIAL** | 実行可能・read-only・部分失敗設計は良い。GSC確定境界と比較契約が不正確 |
| runbook | **PARTIAL** | 両エージェントが同じ入口へ到達できる。判断契約・変更境界・exit code・時間帯が不足 |
| 実測値の秘密管理 | **FAIL** | 実装報告書が禁止事項に自己違反。StorageのPrivate前提も未確認 |

### 修正順序

「第1週、第2週」のような作業都合の分割は不要です。依存順だけを示します。

1. **データ漏えい・成立条件を閉じる**
   - 実装報告書の実測値・実検索語をGit管理版から除去する。
   - `ml-models` bucket がPrivateであることを一度確認する。
   - GA4拡張計測の履歴イベントPVをOFFにし、DebugViewで受入確認する。
2. **比較と失敗時の嘘を止める**
   - GSC date probe、速報/安定比較の分離、派生指標N/A、週報exit code、良品昇格ガード。
   - PV measurement epoch とイベント名移行の連続化。
3. **分類・型・分析可能性を固める**
   - indexableルート分類、集約契約、イベント別param map、TS/Python parity test、必要なGA4 custom dimensions。
4. 上記の短い信頼性修正後、ロードマップ本命の**予測の測定契約**へ進む。

観測日数が必要なのは、修正後のデータを評価するときだけです。コード修正を週単位で待つ理由はありません。

---

## 1. 検証したもの

### 1-1. 読了・静的レビュー

- `AGENTS.md`
- `CLAUDE.md`
- `docs/ANALYTICS_AGENT_RUNBOOK.md`
- `plan/ANALYTICS_REPORT_TO_CODEX_2026-08-26.md`
- `frontend/src/components/GoogleAnalytics.tsx`
- `frontend/src/lib/analytics.ts` と全実イベント呼び出し
- `frontend/src/components/ReportViewTracker.tsx`
- `frontend/src/components/ReservationLinkCard.tsx`
- `frontend/src/components/SecondVenuesList.tsx`
- `scripts/analytics_weekly_report.py`
- `scripts/analytics_report.py`
- 関連テスト、セットアップ文書、GA4管理チェックリスト、sitemap/metadata

### 1-2. read-only 実経路

依頼書で許可された次のコマンドを、そのまま実行しました。

```powershell
python scripts/analytics_report.py --mode latest --days 28 --compare previous --format markdown
```

結果:

- exit code 0
- GA4 / GSC の両方を取得
- 速報日、前期間比、ランディングページ、チャネル、イベント、検索語→ページを出力
- 成功出力に鍵・Bearer token・private key等の秘密値は見当たらない
- **実測値と実検索語は、このGit管理findingsへ転載していない**

このsmokeは「CLIが現在のローカル認証経路で動く」ことを確認しますが、失敗時の例外文字列が
安全であることや、GSCメタデータ経路が機能したことまでは証明しません。

### 1-3. テスト

- Python analytics対象: **54 passed**
- frontend analytics対象: **23 passed**

全緑ですが、後述する反例は現行テストに含まれていません。特に
「本番APIでは返らない形のGSC metadataを合成fixtureで返す」テストがあり、全緑が仕様適合を
保証していない点に注意が必要です。

### 1-4. 外部仕様の照合

一次資料のみを使用しました。

- [GA4 pageviewの公式手動送信方式](https://developers.google.com/analytics/devguides/collection/ga4/views)
- [Search Analytics API query仕様](https://developers.google.com/webmaster-tools/v1/searchanalytics/query)
- [GA4 data freshness](https://support.google.com/analytics/answer/11198161)
- [GA4 event-scoped custom dimensions](https://support.google.com/analytics/answer/14239696)
- [GA4 data retention](https://support.google.com/analytics/answer/7667196)

---

## 2. 8-1 実装レビュー

## 2-1. `GoogleAnalytics.tsx` — pathname判定

対象: `frontend/src/components/GoogleAnalytics.tsx:18-24,33-67,69-84`、
`frontend/src/lib/analytics.ts:181-185`

`shouldSendPageView()` の「enabledかつ直前に送ったpathnameと異なるときだけtrue」という判定は
妥当です。`lastSentPathRef` は「一度でも見たpathname集合」ではなく直前pathnameだけなので、別ページを
挟んだ再訪も正しく計測します。

### 挙動マトリクス

| 操作 | 現行の手動PV | 判定 |
|---|---:|---|
| 初回ハードロード | configから1回 | 静的には妥当。統合テストは未実施 |
| `/a` → `/b` | 1回 | 正しい |
| `/a` → `/b` → `/a` | 再訪時に1回 | 正しい |
| pathnameをまたぐbrowser back/forward | 各遷移で1回 | 正しい |
| 同じpathnameのリンク再クリック | 0回 | 同じ論理ページなので許容 |
| query-only変更 | 0回 | 意図どおり |
| query-only履歴のback/forward | 0回 | 意図どおり |
| `router.refresh()` | 0回 | 同じ論理ページの再取得なので妥当 |
| hashのみ変更 | 0回 | 妥当 |
| 同じURLのハードリロード | 新しいconfigから1回 | 正しい |

### 高: GA4管理画面の設定が成立条件なのに「任意」になっている

`docs/GA4_ADMIN_CHECKLIST.md:1,5-7,11-24` は、履歴イベントに基づくページビューをOFFにする
必要性を正しく説明しています。しかし文書全体を「すべて任意」としています。

GA4公式仕様では、Enhanced Measurementの履歴イベントPVは `send_page_view:false` とも独立して
発火します。これがONなら、次のquery-only変更でGA側から再びPVが飛びます。

- `frontend/src/app/reports/reports-client.tsx:77-110`
- `frontend/src/app/compare/compare-client.tsx:147-152`

従ってこれは任意の改善ではなく、**PV修正の出荷受入条件**です。

オーナーが一度だけ次をDebugViewで確認してください。

- ハードロード = 1PV
- pathname遷移 = 1PV
- query-only変更 = 0PV
- pathnameをまたぐback/forward = 各1PV
- `router.refresh()` = 0PV

日常手作業ではなく、一回限りの受入確認です。

### 中: 現行の手動PV方式はタイミング依存かつ公式方式と異なる

`frontend/src/lib/analytics.ts:182-185` はSPA遷移で次を呼びます。

```ts
gtag("config", GA_MEASUREMENT_ID, { page_path: url });
```

現行GA4公式資料でpageview用に定義されているconfig parameterは `page_title`、
`page_location`、`send_page_view` であり、`page_path` は載っていません。公式の手動方式は:

1. 初期configで `send_page_view:false`
2. 必要な時に `gtag("event", "page_view", { page_location, page_title })`

です。

現在も再度のconfigが既定の `document.location` を使ってPVを発生させるため、件数自体は動く可能性が
高いです。しかし、初回はconfig、SPA遷移は別のconfigという二種類の契約で、次が弱いです。

- 渡した `url` が意図どおり反映される保証
- SPA内の `page_referrer`
- gtag初期化前の高速遷移
- 初回を含めた実送信回数の統合テスト

最終形は、明示的 `page_view` へ一本化し、全経路を同じ送信関数・同じテストに載せることを推奨します。

### テストの正確な評価

`frontend/src/lib/analytics.test.ts:209-234` が検証しているのはpredicateの戻り値です。
初回configとeffectを合わせた実ビーコン総数、back/forward、`router.refresh()`、Enhanced Measurementとの
組合せまでは検証していません。

Claude報告の「初回送信テスト」は、正確には「初回時にpredicateがtrue」というテストです。
静的追跡では初回二重送信を反証できますが、ブラウザ統合の番犬にはなっていません。

### 低: `?dev=1/0` と依存配列

`GoogleAnalytics.tsx:45-67` がpathnameだけに依存するため、同一pathnameでクライアントルーターから
`?dev=1/0` だけ変えてもopt-out同期は走りません。アドレスバーからフルロードする通常手順なら問題ありません。
厳密にするなら「dev query同期effect」と「PV effect」を分ければ、query-only PVを復活させずに直せます。

---

## 2-2. `analytics.ts` — イベントSSOTと型

対象: `frontend/src/lib/analytics.ts:45-82,169-179`

### 良い点

- `ANALYTICS_EVENT_NAMES` からイベント名unionを作る方式は妥当。
- 現在の実呼び出しは全て `store_slug` へ移行済み。
- `official_site_click` と `second_venue_click` のパラメータ組立は、現行データでは妥当。
- `venue_kind="love_hotel"` を既存の `SecondVenuePurpose` に合わせた判断は正しい。

### 高: index signatureは移行後も誤キーを許す

`AnalyticsEventParams` の次の行が、パラメータ契約を実質的に開放しています。

```ts
[key: string]: string | number | boolean | undefined;
```

このため、次が全て型チェックを通ります。

- 必須の `store_slug` を省略
- 旧 `{ slug: ... }`
- typo `{ store_sulg: ... }`
- `report_view` の `report_type` 欠落
- `second_venue_click` の `venue_kind` 欠落
- イベントに無関係な任意キー

実際、`frontend/src/lib/analytics.test.ts:119-134` 自身が旧 `{ slug }` を渡してもコンパイルされています。
移行のための一時措置としては理解できますが、実呼び出しの移行は完了したので残す理由がありません。

イベント別parameter mapへ変えてください。

```ts
type AnalyticsEventParamsByName = {
  store_view: { store_slug: string; store_label: string };
  report_view: { store_slug: string; report_type: "daily" | "weekly" };
  favorite_add: { store_slug: string };
  favorite_remove: { store_slug: string };
  compare_add_store: { store_slug: string };
  range_mode_change: { store_slug: string; mode: RangeMode };
  cost_sim_interact: { store_slug: string; brand: "oriental" | "aisekiya" };
  related_store_click: { store_slug: string; from_slug: string };
  official_site_click: {
    store_slug: string;
    brand: "oriental" | "aisekiya" | "jis";
    destination_domain: string;
  };
  second_venue_click: {
    store_slug: string;
    venue_kind: SecondVenuePurpose;
    destination_domain: string;
  };
};

function track<K extends keyof AnalyticsEventParamsByName>(
  name: K,
  params: AnalyticsEventParamsByName[K],
): void;
```

ユーザー数が少なくても必要です。統計の問題ではなく、誤キーで送ったGA4パラメータは後から修復できず、
カスタムディメンション登録後の観測期間を失うからです。

### 中: TSとPythonはまだSSOTではない

- TS: `frontend/src/lib/analytics.ts:54-65`
- Python: `scripts/analytics_weekly_report.py:76-97`
- TS test: `frontend/src/lib/analytics.test.ts:165-205`

Python一覧は手動複製です。TSテストはTS配列を別のTS期待値と比較するだけで、Pythonとのparityを
検査しません。JSON schemaやコード生成までは不要ですが、PythonテストでTS配列を読み取り、
`report_read` だけを許可されたlegacy差分として集合一致を検査してください。

週報コメント `analytics_weekly_report.py:82-84` も、新イベントを「まだ未実装予定」と書いており、
すでに陳腐化しています。

### 中: GA4 event上位25件から選ぶ方式

`scripts/analytics_weekly_report.py:485-490` は、全eventNameの上位25行を取得してから既知custom eventだけを
選びます。GA自動イベントが増えると、発火数の少ないcustom eventが上位25件から落ちます。

既知名の `IN_LIST` dimension filterを付けるか、少なくともlimitを十分大きくしてください。

### 中: `report_read` → `report_view` は表示上つながっていない

名称変更自体は正しいです。しかし `KNOWN_CUSTOM_EVENTS` に両名を並べただけでは時系列互換になりません。

- `scripts/analytics_weekly_report.py:675-682` はイベント名ごとに別々に前週比較する。
- currentに存在するイベント名だけを表示する。
- 改名直後は旧実績を前週値として使えず、`report_view` が偽の「新規」に見える。

表示・比較時だけ次へcanonicalizeしてください。

```text
report_view_canonical = report_view + report_read
```

移行期間は「旧名を合算」と注記し、送信側で両名を二重送信しないでください。

### 小: `jis` を `oriental` に変換している

`ReservationLinkCard.tsx:56-65` は型制約の都合で `jis` を `oriental` として送ります。現行JIS店舗が
無いため今のデータ誤りではありませんが、将来追加時に静かに誤分類されます。イベント別型で
`official_site_click` だけ3ブランドを許可し、変換を削除する方が安全です。

### GA4 custom dimensions

`docs/GA4_ADMIN_CHECKLIST.md:28-50` は `surface` を登録対象にしますが、現在 `surface` を送る呼び出しは
ありません。一方、二次会導線の意思決定に必要な `venue_kind` が漏れています。

最低限の登録対象は次です。

- 維持: `store_slug`, `brand`, `mode`, `report_type`
- 追加: `venue_kind`
- 現時点では外す: 未送信の `surface`
- 保留: ほぼ定数の `destination_domain`、必要時の `from_slug`

custom dimensionは登録前へ遡及しません。28日後に店舗別・種類別の分析をするなら、必要項目の登録は
「任意」ではなく観測開始条件です。

なおClaude報告 §2-2 の「`report_type` は入れていない」という説明はコードと一致しません。
`frontend/src/components/ReportViewTracker.tsx:13-22` は `report_type` を実際に送っています。

---

## 2-3. `analytics_weekly_report.py`

## `last_confirmed_week()` と `min_lag_days=3`

対象: `scripts/analytics_weekly_report.py:135-170`

### 判定

- **月曜09:00の定期経路だけなら、安全側の選択として妥当**です。
- ただし「APIで確定を確認した週」ではなく、固定ルール上の「確定扱い週」です。
- 月曜実行では必ず丸1週余分に戻るため、GSCはGA4より一週古いデータになります。

`dataState` 省略時が `final` なのは公式仕様どおりです。しかし `final` は「返したデータがfinal」であって、
要求した7日間全日が返った証明ではありません。未確定日の行が欠けた部分週を、合計だけ見て完全週と誤認する
余地があります。

さらにSearch Analytics APIの `startDate` / `endDate` は **PT（America/Los_Angeles）** です。
JST水曜朝に日付差が3日でも、PT上では日曜終了から十分に経っていない場合があります。

### 推奨

最良案は、`dataState="all"` + `dimensions=["date"]` のavailability probeで直近週が完全かを判定することです。
固定ルールを残すなら、名称と表示を「確定週」ではなく「確定扱い週」とし、GSC期間がPTであることを明記します。

運用を単純化する最小案は、定期実行を木曜朝へ移し、前週のGA4/GSCを同じ週で扱うことです。ただしmetadata
probeを入れれば、曜日固定だけに頼る必要はありません。曜日を待つのは作業時間ではなくデータ確定待ちなので、
オーナーの「期間が必要な場合だけ待つ」という方針にも合います。

### 高: 派生指標に偽ゼロが残る

対象:

- `scripts/analytics_weekly_report.py:449-459,519-528,620-624`
- `scripts/analytics_report.py:246-257,394-397`

`gsc.pages` が失敗すると `safe()` は `None` を返します。しかしparse後は空配列になり、
`qualified_clicks_total([])` が0を返します。totalsが成功していれば、ダイジェストは
「有効クリック0」と表示し、警告だけを末尾へ付けます。

これは「取得失敗と実0を分ける」修正が派生指標まで届いていない確定バグです。

修正:

- raw responseの成功/失敗をparse後の空配列と分離する。
- `gsc.pages` 失敗時は `qualified_clicks=None`。
- Markdownは `取得失敗` / `N/A`。
- `gsc.totals` が失敗したらavailabilityも正常値として表示しない。
- 同じ反例のtestを週報・CLIの両方へ追加する。

### 高: 部分失敗でも成功終了し、良品JSONを上書きする

対象:

- `scripts/analytics_weekly_report.py:741-753,808-889`
- `scripts/_supabase_common.py:200-226`

現状は次が全てTask Scheduler上で成功扱いになり得ます。

- 認証情報が消えた
- `google-auth` が無い
- 個別APIが一部または全部失敗
- LINE APIが失敗

さらに週単位の固定Storage pathをupsertするため、再実行時の部分データが既存の完全なJSONを上書きできます。

推奨終了コード:

- 0 = 完全成功
- 3 = 部分取得失敗、または生成できたが配信失敗
- 1 = 認証・依存・主要ソース全滅

初回未設定だけ安全no-opにしたいなら、`--allow-unconfigured` を明示的に使い、Task Schedulerはstrictで
登録してください。設定済み運用で依存や鍵が消えた場合はexit 1が妥当です。

Storageは、最低限warningsがある回にはcanonical週次JSONを更新しないでください。監査用に残すなら
timestamp付きgenerationへ保存し、完全成功時だけcurrentを進めます。この規模ではまず
「部分失敗時は固定pathへの保存をskip」で十分です。

また警告は本文末尾に追加してから2000字で切っているため、長い本文では警告自体が切れる可能性があります。
データ品質を先頭へ置くか、任意セクションだけを切るようにしてください。

### 中: 「raw/full」という説明は正確でない

保存されるのは、APIが返したtop-Nをparseした正規化snapshotです。

- GAページ: top 10
- eventName: top 25
- GSC query: top 10
- GSC page/query×page: top 200

Search Analytics APIは公式に「全行を保証せずtop rowsを返す」と明記しています。
従って「生JSON」「全件」「フル取得」ではなく、**normalized top-N snapshot** と呼ぶべきです。

JSONへ次を保存してください。

- `schema_version` / `measurement_contract_version`
- 各row limit
- `responseAggregationType`
- 取得行数
- source status
- availability source
- timezone
- truncation可能性

新しいダッシュボードは不要です。

---

## 2-4. `analytics_report.py`

### 良い点

- argparseあり。
- 保存・LINE送信・Supabase書き込みの機能自体が無い。
- `--mode latest|range`、期間、形式、比較の入口が分かりやすい。
- source別の部分失敗を保持し、0/3/1を意図した設計は良い。
- ローカル実認証経路でexit 0を確認できた。
- GA4のtoday/yesterdayを「値が動き得る」と表示する考え方は妥当。

### 最重要: GSC metadataの読み方がリクエストと一致しない

対象: `scripts/analytics_report.py:128-143,239-244`、
`tests/test_analytics_report.py:91-108`

公式仕様で `metadata.first_incomplete_date` が返るのは:

- `dataState="all"`
- `dimensions=["date"]`
- 要求期間に未確定データがある

場合だけです。現行はdimensionなしtotalsへ `dataState="all"` を付け、そのレスポンスからmetadataを読もうと
します。そのため本番ではmetadata経路に入らず、ほぼ常に `as_of - 3日` のrule fallbackです。

smoke時に表示日がもっともらしく見えたことは、固定ルールと実際がその日に一致しただけで、metadata解釈の
検証ではありません。現行テストは、本番では返らない形の合成レスポンスを作っており、誤った仮定を固定しています。

修正:

1. totalsとは別に `dimensions=["date"]`, `dataState="all"` のprobeを追加する。
2. `availability_source=metadata|rule|unavailable` を出力する。
3. metadataなら「APIメタデータ」、ruleなら「推定」、probe失敗ならN/Aとする。
4. probe失敗をexit 3へ反映する。
5. GSCの基準日・期間をPTで計算・表示する。

### 高: 「最新」と「比較可能」を一つの期間へ混ぜている

対象: `scripts/analytics_report.py:85-125,219-225,260-276`、
`docs/ANALYTICS_AGENT_RUNBOOK.md:38-40,51-53`

標準コマンドのcurrent 28日は当日までを含みます。GA4は直近日、GSCは直近数日が速報です。一方previousは
確定期間です。小母数では数件の未反映だけで割合が大きく動くため、現在のdeltaは判断用の比較ではありません。

次の二つを同じコマンドで出してください。

- **latest snapshot**: 当日まで。速報として表示し、判断用deltaを付けない。
- **stable comparison**: sourceごとの安定cutoffまでの28日 vs その直前28日。

GA4とGSCでcutoffが異なって構いません。無理に日付を合わせず明記します。stable windowを作れない場合は
deltaを省略し「比較保留」としてください。

GA4のtoday/yesterdayを速報扱いにするheuristicは許容できます。ただし2日前を「確定」と保証するものでは
ありません。公式には処理中24〜48時間は値が変わり得るため、安定比較は `as_of - 3日` 以前を推奨します。

### 中: GSC出力がSEOの意思決定に不足

`analytics_report.py:246-249,405-419` はqueryごとのimpressions/positionを取得していますが、Markdownでは
ほぼクリック数だけを出します。query×pageもクリック降順で、クリック0の同率行はAPI仕様上任意順です。

この規模で実際に効くのは、新画面ではなく同じデータの次の4リストです。

- クリック上位
- 表示回数上位
- 高表示・低CTR
- 平均4〜20位で表示のある改善候補

query / query×page のlimitをまず1000程度へ増やし、ローカルで分類してください。週次LINEは短いままでよく、
on-demand CLIだけ詳細化すれば十分です。「全件」ではなく「APIが返した上位N行」と表示します。

### 中: 順位帯の契約

`scripts/analytics_weekly_report.py:406-415` は `position=None` または0を1〜3位へ分類します。
またCLIの「順位帯（クエリ数）」は、全クエリではなくクリック上位25行の非加重件数です。

- `position <= 0`、非有限、欠損は `unknown`
- 現行のままなら「クリック上位25検索語内」と表示
- 可能なら表示回数も併記

としてください。

### 終了コード

0/3/1という意図は良いです。ただし実装・文書は次で不一致です。

- argparseのusage/choiceエラーは標準exit 2。
- `--as-of`形式やrange依存引数の検証は認証後。
- runbookは未セットアップを「エラーではない」と書くが、CLIはexit 1。
- runbookにexit 3時の分析方法がない。

標準化案:

- 0 = 完全成功
- 3 = 部分成功
- 1 = 認証・実行時致命
- 2 = CLI使用法・引数不正

引数と期間をenv読込・認証より先に検証してください。runbookにはexit 3なら成功部分だけを分析し、欠損を
必ず回答へ書く、exit 1/2なら分析を中止する、と明記します。

---

## 2-5. `ANALYTICS_AGENT_RUNBOOK.md`

### 実際に使えるか

**ローカルfilesystemと認証情報へ到達できるClaude Code / Codexでは使えます。**
今回、runbookの標準コマンドをそのまま実行できました。

ブラウザ版ChatGPT単体では実行できないという注記も正しいです。これはコードで解消できる欠陥ではなく、
秘密鍵をブラウザ版へ渡さないための正しい制約です。したがって「ClaudeとChatGPTの両方」は、
**同じローカルリポジトリを操作できるエージェント同士**という範囲で達成されています。

### 足りない回答契約

runbookには次を追加してください。

1. GA4とGSCそれぞれの期間・timezone。
2. latest snapshotとstable comparisonの分離。
3. source statusとexit codeの扱い。
4. PV measurement epochをまたいだ比較禁止。
5. `report_read` / `report_view` の移行合算。
6. クリック上位だけでなく、高表示・低CTR機会を見ること。
7. 回答を「今やる」「データ待ち」「やらない」に分けること。
8. 実測値・検索語はチャット回答内だけにし、Git管理ファイルへ転記しないこと。
9. 固定のSEO観測終了日を過ぎたら評価して注記を更新すること。
10. store別/event parameter分析にはGA4 custom dimension登録が必要であること。

### 文書の矛盾・事実誤認

- `docs/ANALYTICS_AGENT_RUNBOOK.md:27-28`: 未セットアップは「エラーではない」だがCLIはexit 1。
- `docs/ANALYTICS_SETUP.md:126-134` と `docs/GA4_ADMIN_CHECKLIST.md:55-66`:
  2か月保持だと標準集計の前週比・長期値が消えるという説明は誤り。GA4公式ではdata retentionは
  standard aggregated reportsへ影響せず、主にExplorations/funnelへ影響する。14か月推奨自体は維持してよいが、
  理由を将来のevent/user-level分析へ直す。
- `docs/ANALYTICS_SETUP.md` のGSC遅延説明と `analytics_weekly_report.py:691` の「直近2日」は、
  現在の一週後退・3日規約と一致しない。
- Claude報告 §3 の「UTM命名規約はrunbookに記載済み」は事実と異なる。runbookにUTM記述は無い。

---

## 2-6. 秘密管理・Git運用

### 最優先: 実装報告書が自分の禁止事項に違反している

対象: `plan/ANALYTICS_REPORT_TO_CODEX_2026-08-26.md`、commit `3894abe`

確認できた事実:

- 同ファイルはGit追跡対象。
- 本文に実測由来のアクセス件数と実検索語の文字列がある。
- `main` と `origin/main` は同期しており、対象commitはremote履歴にある。
- 同文書 §8-5 とrunbookは、実測値・実検索語をGit管理ファイルへ書かないよう明記する。

本レビューはread-only制約のため削除・履歴変更をしていません。このfindingsにも値・語を転載していません。

次の認可された修正で:

1. 現行ファイルの実測値・実検索語を範囲表現、合成例、または `[REDACTED]` へ置換する。
2. 今後の詳細実測メモは、Git除外済みであることを確認した `plan/_local/` へ置く。
3. remote履歴書き換えが必要かは、repoの公開範囲とオーナーの機密性判断で決める。

履歴書き換え・force pushは破壊的なので、オーナーの明示承認なしに実行しないでください。今回露出したのは
認証鍵やtokenではないため、認証情報のrotationまでは不要です。

### 高: `ml-models` がPrivateか未確認

`scripts/analytics_weekly_report.py:741-753` は実検索語とquery×pageを既定 `ml-models` bucketへ保存します。
一方、`plan/EXTERNAL_REVIEW_PROGRESS.md:168-171` では、そのbucketがPrivateか今もオーナー側確認事項です。

今回の実装により、未確認bucketへ検索語を保存する影響が大きくなりました。次回自動保存前に一度確認してください。

可能ならジョブがread-only bucket metadataを確認し、publicなら検索語を含むuploadをfail closedするのが安全です。
専用有料サービスや新ダッシュボードは不要です。

### 低: 失敗例外のscrub

`analytics_report.py:184-190,465-469` と `analytics_weekly_report.py:449-459,833-841` は例外文字列を
そのまま出力します。成功smokeに秘密が無かったことは、失敗例外が安全である証明ではありません。

- 公開出力は例外class・HTTP status・固定メッセージに限定。
- 共通scrubberでBearer/private key/API keyらしい値を除去。
- 合成秘密文字列を含む例外テストを追加。

を推奨します。

---

## 3. Claude報告に対する事実訂正

| Claude報告の説明 | レビュー結果 |
|---|---|
| 初回PV送信をテストした | predicateをテストしただけ。静的には二重送信なしだが実ビーコン統合テストではない |
| 検索には既存の専用イベントがある | **誤り**。`reports-client.tsx:105-110` はstate/URL更新だけで、検索イベントは無い |
| `report_type` は入れていない | **誤り**。`ReportViewTracker.tsx:21` が送っている |
| TS/PythonはイベントSSOTでズレに気づける | 名称は現時点で一致するが、cross-language parity testは無い |
| GSC metadataから確定日を算出 | 現行dimensionなしrequestではmetadataは返らず、実際は固定3日rule |
| 生JSONへ全件・層2相当をフル保存 | top-Nをparseしたnormalized snapshot。APIも全行を保証しない |
| UTM命名規約はrunbookに記載済み | **誤り**。runbookに該当記述は無い |
| 実測値・検索語はGitにコミットしていない | **誤り**。この実装報告書自身が該当する |
| GA4保持2か月では前週比・長期aggregateが取れない | **誤り**。標準集計レポートは保持設定の対象外 |

これらはClaudeの実装全体を否定するものではありません。報告の正確性と、次の修正優先順位を正すための訂正です。

---

## 4. 8-2 見送り7項目への回答

## 4-1. KPI 8分類 — **全面導入は見送りでよい**

同意します。現状の小規模トラフィックで8分類を毎週読み分けても、分類数ほど意思決定は増えません。
予測の測定契約より優先する理由もありません。

ただし、8分類を見送ることと、測定契約を持たないことは別です。週次とCLIは次の最小4問へ答えれば十分です。

1. **獲得**: 確定済みGSCで、現役indexable面と店舗選択面への流入はどうか。
2. **利用意図**: store / compare / range / cost / reportの利用はあるか。
3. **送客**: official / second venueへのクリックはあるか。見えた回数に対してどうか。
4. **品質**: 速報・欠損・計測定義変更をまたいでいないか。

これは新しい8分類フレームワークではなく、既存値を誤読しないための最小契約です。

## 4-2. IntersectionObserver露出群 — **全面群は見送り、送客2面の分母だけ反論**

広範な `decision_card_view` 群は不要です。しかし新設した2クリックには露出分母がありません。

- `official_site_click`
- `second_venue_click`

クリックが少ないとき、現状では「カードまで見られていない」「見たが押さない」「対象ページ自体が少ない」を
区別できません。またClaude報告の評価条件は「有効露出が一定数」としていますが、露出を測らずにその条件を
直接判定できません。

次の2つだけは、データ蓄積を今から始める価値があります。

- `official_site_view`
- `second_venue_view`

一つの再利用hookで、50%以上が1秒表示、1 pageviewにつき1回、程度で十分です。

変わる意思決定:

- 露出が低い → 配置・折りたたみ・スクロール導線
- 露出あり、CTR低い → 文言・リンク先・信頼材料
- 露出・CTRとも高い → 他画面へ展開
- 露出母数不足 → 結論せず観測継続

毎日の作業は増えません。広い露出基盤ではなく2面だけなので実装コストも小さいです。ただし優先順位は、
本書のP0/P1データ品質修正の後、予測の測定契約を遅らせない範囲です。待つ理由はコーディング時間ではなく、
修正後の露出データ蓄積です。

## 4-3. `report_engaged` / `report_complete` — **見送りでよい**

現時点のレポート閲覧母数では、滞在・読了を加えても内容改善の判断に耐えません。`report_view` の意味を正した
ことをまず活かすべきです。`report_view` が十分蓄積し、レポートを改善する具体的な意思決定が発生した時に
再検討すればよいです。

## 4-4. 流入UTM分析 — **見送りでよい。ただし報告理由は訂正**

広告・提携・固定SNS施策が無い間は、inbound UTM分析を作っても判断は変わりません。見送りに同意します。

ただし「命名規約がrunbookにある」は事実ではありません。次の4行程度だけ先に残してください。

- inbound campaignを始める時だけ有効化する。
- source / medium / campaignをlowercase ASCIIの固定語彙で決める。
- outboundの `utm_source=megribi` とinbound campaignを混同しない。
- 施策開始前にGA4 Realtimeで受信確認する。

分析機能はcampaign開始時で構いません。

## 4-5. 公式SDK移行 — **見送りでよい**

同意します。今回残った問題はSDKではなく、期間・集約・欠損・分類の契約です。SDKへ替えても自動では直りません。
生RESTのまま、レスポンスshape、`responseAggregationType`、availability probe、retry、scrubを固める方が先です。

## 4-6. 週報の全面二層化 — **新画面は見送り。snapshot契約だけ強化**

新しい管理画面は不要です。短いLINE要約 + machine-readable snapshot + on-demand CLIで十分です。

ただし現行snapshotはfull raw dataではありません。前述のschema/row limit/aggregation/coverage/source statusを
持たせ、部分失敗でcanonicalを上書きしないことは必要です。これは新しい分析UIではなく保存契約の修正です。

## 4-7. A/Bテスト — **見送りでよい**

同意します。現母数では割付後の各群がさらに小さくなり、意思決定を遅くします。まず計測定義を固定し、
単一変更の時系列観測で十分です。

---

## 5. 8-3 この規模で実際に効く追加改善

## 5-1. PV・イベントのmeasurement epochを機械可読にする

PV定義変更は文書注記だけでなく、コードが比較可否を判断できるようにしてください。

- `PV_DEFINITION_CHANGE_AT` または `measurement_contract_version`
- 変更日当日は `mixed`
- 変更日翌日以降を新epoch
- current/previousのどちらかが境界をまたぐ、またはepochが違う場合:
  - PV deltaをN/A
  - PVベースのtop growthをN/A
  - users/sessionsは通常比較
- 両期間が完全に新epochになったら自動再開

routeごとに過大計上率が違うため、単一係数で過去PVを逆補正しないでください。どうしても参考系列を作るなら、
store_view等で検証した「推定補正」として別系列にし、GA原値を上書きしないことです。

同じversion情報をprivate weekly snapshotへ保存すると、将来のClaude/Codexも自動で境界を認識できます。

## 5-2. GSCページ分類をroute契約へ合わせる

現行 `classify_page_path()` はprefixだけで分類し、実routeと一致しません。

- `/reports` rootをnoindex detailと同じ `report` にする。
- `/compare` を `other` にする。
- 空文字をhomeにする。
- 未知store/area/blog slugもactive扱いにする。
- closed slugをfrontendから手動複製する。

最低限の内部分類:

- `home`
- `stores`
- `store_active`
- `area`
- `compare`
- `reports_hub`
- `blog_hub`
- `blog_article`
- `report_detail_noindex`
- `closed`
- `utility`
- `unknown`

LINEへ全部出す必要はありません。内部集計を次へ畳みます。

- 現役indexable到達
- 店舗選択に近い到達
- content discovery
- 除外・要診断

sitemapの静的routeが分類テストに全て現れる番犬を追加してください。

## 5-3. 「有効クリック」の集約契約を分ける

GSC totalsはpage dimensionなし、qualifiedはpage dimension行の合計です。Google公式仕様ではpageでgroup/filterした
場合はproperty aggregationを使えないため、両者は同一分母ではありません。

次を別名で出します。

- `search_clicks_property_total`
- `page_rows_click_total`
- `indexable_destination_clicks`
- `decision_surface_clicks`
- `diagnostic_clicks`（noindex/closed/unknown）

割合を出すなら分母は同じpage aggregationの `page_rows_click_total` に限定し、property totalは別の総数として
併記します。rowLimitで切れた可能性も表示します。

## 5-4. 指名分類を三分する

`megribi` 表記追加は正しい修正です。ただし現在の関数はサイト名だけを指名とし、店舗チェーン名を含む
ナビゲーショナル検索を「一般」にします。「指名」というラベルのままだとgeneric SEOを過大評価します。

次の三分類が実用的です。

1. `site_brand`: めぐりび / メグリビ / meguribi / megribi
2. `venue_brand`: オリエンタルラウンジ / Oriental Lounge / 相席屋 / Aisekiya 等
3. `generic`: 地名 + 相席、混雑、料金等

NFKC + casefold + 空白/ハイフン正規化までで十分です。実測に無い大量の誤字辞書は不要です。
GSCは一部queryをprivacy上省略し、APIも全行を保証しないため、行合計をproperty全体の完全な構成比とは扱わないで
ください。

## 5-5. 内部リンクの `?store=` を全除去する

残存箇所は10件です。

- `frontend/src/components/StoreCard.tsx:106-108`
- `frontend/src/components/home/HomeTonightTop5.tsx:68`
- `frontend/src/components/home/HomeLastVisitedSection.tsx:43`
- `frontend/src/app/mypage/mypage-client.tsx:300,375,428`
- `frontend/src/app/compare/compare-client.tsx:534`
- `frontend/src/app/reports/reports-client.tsx:442`
- `frontend/src/app/reports/daily/[store_slug]/page.tsx:84`
- `frontend/src/app/reports/weekly/[store_slug]/page.tsx:233`

削除を推奨します。

- `/store/[id]` はpath slugを優先し、queryは読まれない。
- canonicalはすでに `/store/<slug>`。
- 外部の古いURL互換は、内部生成を消しても維持できる。
- `pagePath` はqueryを除くため現在の週報top pageを直接分割する確定バグではないが、
  `pageLocation` / `pagePathPlusQueryString` / URL探索・共有には不要な枝が残る。

低コストなURL正規化として一括削除し、受入テストで内部 `/store/` linkに `?store=` が0件であることを固定します。

## 5-6. 送客露出2面だけを計測する

§4-2のとおり、広い露出基盤ではなく送客クリックの分母だけを取ります。実装後はcustom dimensionの
`surface` を実際に送るか、event name自体を面ごとに分けます。

## 5-7. 最新分析の出力契約

「分析して」と言われた際、同じCLI結果からClaude/Codexが次の順で回答する形へrunbookを固定すると、
週次レポート以上の新画面は不要です。

1. データ品質・確定境界
2. latest pulse（速報）
3. stable 28日比較
4. acquisition（GSC/organic）
5. intent events
6. outbound eventsと分母
7. 今やる / データ待ち / やらない

週次LINEはこのうち1、3、4、5、6の短い要約だけで十分です。

---

## 6. 8-4 未解決の4懸念への直接回答

## 懸念1. PV定義の不連続をどう扱うか

**過去GA4値を上書き・一律補正しない。measurement epochを導入し、境界越しのPV比較を自動で止める**のが
推奨です。

- 変更日はmixedとして除外。
- CLI/週報にversionと比較可否を出す。
- users / sessions / GSC clicksは境界越しでも継続指標として使う。
- PVとPVベースtop growthは、両期間が同じ新epochになるまでN/A。
- 必要ならGA4管理画面へ一度annotationを残すが、正本はコード側version。
- 推定補正を作る場合も別系列で、GA原値は保持。

注記だけより強く、将来のAIエージェントの誤読も防げます。

## 懸念2. 残る `?store=` を消すか

**内部リンクからは全て消すべきです。**

現時点のPV総数を直接壊す重大バグではありませんが、非正規URLを内部から作り続ける理由がありません。
古い外部URLを受けるfallbackは残し、内部生成だけcanonical pathへ統一します。実害が小さいから放置するより、
機械的・低リスクな正規化として今直す方がよいです。

## 懸念3. `/blog` を有効検索クリックへ含めるか

**「現役indexableな到達」という定義なら含めるのが妥当**です。ブログ検索流入は正当に獲得した流入です。

ただし店舗選択に近いクリックと同価値にはしません。

- `indexable_destination_clicks`: blogを含む
- `decision_surface_clicks`: store / stores / area / compare等
- `content_discovery_clicks`: blog
- `diagnostic_clicks`: noindex report / closed / unknown

と分けます。

現行定義は `/reports` hubと`/compare`を除外し、page/propertyの集約契約も混ぜるため、修正前の「有効クリック」
値をKPIとして固定しないでください。

## 懸念4. 分類ロジックの他の見落とし

確認できた見落としは次です。

- `/reports` hub とnoindex report detailの混同
- `/compare` の除外
- 空/不正pageをhome扱い
- 存在しないstore/area/blog slugをactive扱い
- closed slugの手動二重管理
- `position=None/0` を1〜3位扱い
- 順位帯が全queryではなくクリック上位25行の件数
- GSC日付をJSTのように扱うが実際はPT
- サイト指名と店舗チェーン指名を同じ「一般」に混ぜる
- Unicode/空白/ハイフン正規化なし
- page rowsとproperty totalsを同一母集団のように表示

テストは個別例の追加だけでなく、sitemap/metadata、closed集合、イベントSSOTを正本から突き合わせる番犬にして
ください。

---

## 7. Claudeへ渡す実装チェックリスト

### 必須（クリーン観測開始の前提）

- [ ] GA4 Enhanced Measurementのhistory pageviewをOFF確認し、DebugView 5経路を受入。
- [ ] Git管理された実装報告書から実測値・実検索語を除去。privateメモは `plan/_local/` へ。
- [ ] `ml-models` bucketがPrivateか確認。publicならanalytics uploadをfail closed。
- [ ] GSC availabilityをdate dimension probeへ修正し、PT・sourceを出力。
- [ ] latest snapshotとstable comparisonを分離。
- [ ] `gsc.pages` 失敗時のqualified指標をN/Aにする。
- [ ] PV measurement epochを実装し、境界越しPV delta/top growthを抑止。
- [ ] `report_read + report_view` を表示時にcanonical合算。
- [ ] 週報の部分失敗をexit 3、致命をexit 1にし、部分JSONをcanonicalへ昇格しない。

### 続けて行う低コスト修正

- [ ] event別parameter mapへ移行し、index signatureを削除。
- [ ] TS/Pythonイベントparity testを追加。
- [ ] GA4 custom dimensionsを実送信値に合わせる（`venue_kind`追加、未送信`surface`整理）。
- [ ] GSC page分類を `/reports` hub、detail、`/compare` まで正す。
- [ ] page aggregation内の分母とproperty totalを分離。
- [ ] position unknown、top-N/aggregation/coverage metadataを追加。
- [ ] 内部 `/store/*?store=` linkを0件へ。
- [ ] GA4明示的 `page_view` 方式と実ブラウザ番犬へ移行。
- [ ] UTM起動条件と命名規約だけrunbookへ追加。
- [ ] GA4保持期間、GSC遅延、CLI exit codeの文書誤りを修正。
- [ ] 失敗例外の秘密らしい値をscrubするtestを追加。

### データ蓄積が必要なもの

- [ ] 修正後のPV/イベントは、最初の完全な新epoch日から28日または十分な母数まで観測。
- [ ] 送客2面の露出分母を追加した場合、露出母数が十分になるまでCTR判断を保留。
- [ ] SEO施策はSearch Consoleの反映遅延を含むクリーンな28日窓が揃うまで効果断定を保留。

これは作業を週単位に分割する指示ではありません。待つのは評価にデータ蓄積が必要な項目だけです。

---

## 8. 受入テスト

最低限、次の番犬を追加してください。

### PV

- 初回ハードロードで実 `page_view` 1回。
- pathname遷移ごとに1回。
- query-only / hash-only / `router.refresh()` は0回。
- pathをまたぐback/forwardは各1回。
- Enhanced Measurement OFFのDebugView実確認。
- measurement epochをまたぐPV deltaはN/A。

### Event

- 全イベントの必須param欠落・typoがTypeScript error。
- Pythonイベント集合はTS集合 + 許可legacy aliasだけ。
- `report_read` と `report_view` のcurrent/previousが一つの論理指標に合算。
- 既知custom eventがGA全イベントtop-Nの外でも取得対象になる。

### GSC / CLI

- availability probeが必ず `dimensions=["date"]` を送る。
- dimensionなしresponseではmetadata確定扱いにしない。
- probe失敗時はavailability N/A + exit 3。
- current速報とstable comparisonのperiodが別。
- `gsc.pages` 失敗時は有効クリックN/A。
- `/reports` hubと`/compare`はindexable、report detailは除外。
- position `None/0/NaN` はunknown。
- GSC期間がPTとして計算・表示される。
- 0/1/2/3 exit code。

### Weekly quality gate

- 部分失敗はexit 3。
- 全滅・認証・依存失敗はexit 1。
- 部分失敗時にcanonical weekly JSONを上書きしない。
- warningは2000字切り詰め後も必ず残る。
- public bucket判定時はqueryをuploadしない。

### Secret safety

- 合成例外へBearer/private-key/API-key風文字列を入れ、stdout/stderrから消える。
- 実測値・実検索語がGit追跡ファイルへ入っていないことをCIまたはレビューgrepで確認。

---

## 9. 最終推奨

1. Claudeの実装方向は採用する。PV pathnameガード、イベント名union、送客イベント、read-only CLIを戻さない。
2. ただし「8/26からクリーン観測開始」は撤回し、GA4管理画面確認とP0/P1修正後の最初の完全日を新epoch開始日にする。
3. SEO観測はPVとは別契約なので継続できるが、GSCのPT・速報境界・分類修正前の値を固定KPIにしない。
4. 週次運用は、新画面を作らず **短いLINE + versioned normalized snapshot + on-demand CLI** で十分。
5. 広いKPI体系、SDK移行、A/B、report engagementは見送る。
6. 送客だけはクリックの意味を判断するための露出分母を小さく追加し、データ蓄積を始める。
7. 上記の短い信頼性修正後、ロードマップ本命の予測測定契約へ進む。

最も重要なのは、機能を増やすことではなく、**速報・確定・欠損・集約・計測定義変更を、コードが自動で区別すること**です。
これができれば、ClaudeとCodexのどちらへ「最新を分析して」と頼んでも、同じ数字を取得するだけでなく、
同じ条件で「今判断してよいか」まで答えられます。
