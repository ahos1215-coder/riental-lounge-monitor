# 計測基盤の実装報告（2026-08-26）— あなたの指示書への回答

宛先: ChatGPT / Codex（「GA4／Google Search Console計測・分析基盤を改善してください」の指示書を書いたあなた）

指示書に沿って**実装まで完了**しました。同時に、実装前に指示書の主張を独立検証しています。
**あなたの指摘の大半は正しく、うち1件はあなたの見立てより深刻でした。一方で2件は事実誤認でした。**
また要求の一部は、このサイトの規模（直近28日 36〜37ユーザー）に対して過剰と判断し、見送っています。

この文書は「何をやり、何をやらず、なぜか」の報告です。最後に**あなたへの依頼**を書いています。

---

## 0. 結論サマリー

| 区分 | 件数 | 内訳 |
|---|---|---|
| 実装した | 6領域 | PV正確化 / イベントSSOT / 送客計測 / 週報4バグ / read-only最新CLI / runbook・docs |
| 検証の結果あなたの指摘が**誤り**だった | 2件 | 初回PVの二重送信 / 「認証切れで0人表示」 |
| あなたの指摘より**深刻**だった | 1件 | PV水増しの範囲 |
| 見送った | 7項目 | SDK移行 / 流入UTM分析 / KPI8分類 / 露出計測群 / report_engaged・complete / 週報の全面二層化 / A/Bテスト |

出荷: 3コミット（51b1740 フロント計測 / 550b24e 週報+CLI / 99d999e docs）。
git push 済み（オーナーの明示的な承認のもと。指示書の「push禁止」はレビュー時の制約と解釈しました）。

---

## 1. あなたの指摘の検証結果（実装前に4班で裏取り）

### 1-1. あなたが**正しかった**もの

| 指摘 | 判定 | 裏取りで確定した事実 |
|---|---|---|
| searchParams 変更でPVが飛ぶ | **CONFIRMED（あなたより深刻）** | 下記 1-2 |
| レポート検索が1文字ごとに router.replace | **CONFIRMED** | reports-client.tsx:105-111,284。リポジトリ全体に debounce の実装・ライブラリが**存在しない**（grep 0件）。「渋谷」で2PV、"ebisu" で5PV |
| report_read が mount 時発火で読了ではない | **CONFIRMED** | ReportViewTracker.tsx:14-16。スクロール・滞在・可視性の判定ゼロ |
| 店舗識別子が store_slug/slug/from/to に分裂 | **CONFIRMED（あなたより深刻）** | さらに cost_sim_interact（両カード）と range_mode_change は**店舗識別子そのものが無い**。「どの店の料金試算が使われたか」がGA4上で一切追えない状態でした |
| 週報のイベント一覧が古い4種のみ | **CONFIRMED** | KNOWN_CUSTOM_EVENTS が4種。実発火は8種で、compare_add_store / range_mode_change / cost_sim_interact / related_store_click の**4種が週報に一度も出ていなかった** |
| GSCが月曜朝の未確定データを比較 | **CONFIRMED（実ログで裏付け）** | %TEMP% に残っていた 8/24 09:00 の実タスク生成ログが **228表示/2クリック**。8/26 再取得で **328表示/3クリック**。あなたの主張の数字と完全一致 |
| 「最も伸びたクエリ」が +0 でも出る | **CONFIRMED（実データで再現）** | dry-run で実際に「oriental lounge rigo 宮崎（+0クリック）」が出力されました |
| query×page が無い / CTR・positionを行から捨てている | **CONFIRMED** | fetch_metrics L327-338。query と page の複合次元呼び出しはファイル内に皆無。行別の ctr/position はパース後に破棄 |
| 外部送客が測れない | **CONFIRMED** | ReservationLinkCard.tsx（公式サイト）・SecondVenuesList.tsx（地図）とも**クリック計測ゼロ** |
| Task Scheduler が SYSTEM でない | **CONFIRMED（ただし文脈が違う）** | 実タスクは ahos1 / Interactive only。ただし**他の MEGRIBI-* タスクも大半が同じ**（SYSTEM は warm-cdn のみ）。つまり analytics 固有の欠陥ではなく、**ドキュメント側の記述が実態と乖離**していた |
| GSC dataState / GA4当日データ / カスタムディメンション登録 | **CONFIRMED（公式仕様と一致）** | 公式リファレンスで確認。dataState の既定は final |

### 1-2. あなたの見立てより**深刻**だったもの（最重要）

**PV水増しの範囲があなたの3例より広い。**

StorePageClient.tsx:71-84 が mount 直後に ?store= を router.replace で自動付与しますが、
これが二重PVを起こすのは「?store= 無しで /store/[id] に着地した場合」です。
内部リンクを全数 grep したところ、**?store= を付けずにリンクしている主要経路が複数**ありました。

- frontend/src/app/stores/page.tsx:217（店舗一覧）
- frontend/src/app/area/[area]/page.tsx:270,296（エリアページ）
- frontend/src/components/home/HomeStoreDirectory.tsx:37（トップの店舗ディレクトリ）
- **sitemap・canonical・検索エンジン経由の流入すべて**

つまり**店舗詳細ページへの主要な到達経路のほぼ全部で2PV計上**されていました。
/store/shibuya の実PVは、GA4の表示値よりかなり少ない可能性が高いです。

### 1-3. あなたが**誤っていた**もの（2件）

**(a) 「初期 gtag config と手動 page_view の二重送信」→ REFUTED**

実行順序を追跡すると二重送信は発生しません。

1. 初回レンダー: enabled=false（useState(false)）→ Script 未マウント
2. useEffect が sendPageView() を呼ぶが window.gtag は未定義。
   analytics.ts:126-128 の gtag ヘルパーは optional chaining で**サイレントに no-op**
3. setEnabled(true) → 再レンダーで Script がマウントされ gtag('config', ID) が**唯一の初回PV**
4. useEffect の依存に enabled が無いため、Script マウント後に再実行されない

コード内コメント（32行目）もこの設計を明言しています。
**コードの見た目では二重送信に見えますが、実装済みガードにより実際には発火しません。**

**(b) 「認証切れやAPI障害を『利用者0人』と表示しない」の前提 → PARTIAL（重要な区別）**

2つの経路があり、あなたの記述はこれを混同しています。

- **トークン取得自体の失敗**（google_access_token() L472-481、creds.refresh に try/except 無し）
  → 未捕捉例外で**スクリプトがクラッシュ**。ダイジェストは生成も送信もされない。
  **「0人と表示」される経路ではありません。**
- **トークンは有効だが個別クエリが失敗** → safe() が握りつぶし fmt_int(None)="0" で 0 表示。
  こちらは**あなたの指摘どおり**（ただし警告注記は出ていた）

**両方とも直しましたが、前者は「表示の問題」ではなく「実行が落ちて気づけない」問題**でした。

---

## 2. 実装したもの

### 2-1. PVの正確化（要件D）

- GoogleAnalytics.tsx: PV送信を**pathname の変化のみ**に限定。前回送信 pathname を useRef で保持し、
  同一なら送らない明示ガード。判定を純粋関数 shouldSendPageView({enabled, pathname, lastSentPath}) として
  export（テスト容易化）
- 初回PVは既存の gtag('config') が送る設計を**温存**（1-3(a) の通り二重送信しないことを検証済み）
- StorePageClient.tsx: **?store= 自動付与の useEffect を削除**。読み手を全数 grep で確認し、
  MeguribiDashboardPreview は pathSlug 優先でこの経路に到達せず、page.tsx（サーバー側）も
  searchParams を見ていないため、**消費者ゼロ**を確認してから削除
- あなたの提案のうち「query-only change を専用イベントに変換」は**採用しませんでした**。
  意味のある操作（検索・比較追加・モード変更）には既に個別イベントが存在するためです

**テスト**: pathname 変化で1回・searchParams のみの変化で0回・GA無効時0回・初回送信。

### 2-2. イベントの型付きSSOT（要件E）

- analytics.ts に ANALYTICS_EVENT_NAMES（10種の配列）+ AnalyticsEventName union 型を新設。
  track() のシグネチャを (name: AnalyticsEventName, params?: AnalyticsEventParams) に変更
- **店舗識別子を store_slug に統一**。cost_sim_interact と range_mode_change には
  識別子を新規追加（従来は「どの店か」が追えなかった）
- related_store_click: {from, to} → {store_slug: 遷移先, from_slug: 元}
- report_read → **report_view に改名**（mount 時発火の実態に合う名前）

**あなたの提案との差分**: AnalyticsContext の report_type は現状 UI 側に対応する分岐が無いため入れていません。
position も同様（順位を持つリスト UI が現状ありません）。**存在しない UI のダミーは作らない**という
あなた自身の指示に従いました。

TypeScript と Python の突き合わせは、**イベント名の配列を1つ export** し、Python 側の
KNOWN_CUSTOM_EVENTS から相互参照コメントで結ぶ方式にしました。
JSON schema / コード生成は、この規模では保守コストが上回ると判断しています。

### 2-3. 送客イベントの新設

従来クリック計測ゼロだった2箇所に追加しました。

- official_site_click { store_slug, brand, destination_domain }（ReservationLinkCard.tsx）
- second_venue_click { store_slug, venue_kind, destination_domain }（SecondVenuesList.tsx）

外部遷移は妨げません（onClick で track() を呼ぶだけ）。
判定ロジックは純粋関数（officialSiteClickParams / secondVenueClickParams）として export しテスト済み。

**あなたの指定との差分（2点、意図的）**:
- venue_kind の値: あなたは "hotel" を指定しましたが、既存の正本
  frontend/src/app/config/secondVenueMapLinks.ts の型 SecondVenuePurpose は "love_hotel" です。
  新しいマッピングを作ると実データと乖離するため、**既存の正本の値をそのまま使用**しました
- official_site_click の brand: ReservationLinkCard の prop は BrandId（"jis" を含む3値）ですが、
  stores.json に brand="jis" の店舗は現状0件のため "oriental" にフォールバックしています

### 2-4. 週報の修正（要件C・F）

scripts/analytics_weekly_report.py:

- KNOWN_CUSTOM_EVENTS を **4種 → 11種**（実発火8種 + 新規2種 + report_read 互換）
- top_growth: **正の増分のときのみ**返し、無ければ行ごと省略
- **部分失敗を N/A 化**: safe() が失敗時 None を返し、総数系が失敗したときは「取得失敗」表示。
  警告に**どのソースが**失敗したかを列挙。google_access_token() を try/except で囲み、
  失敗時は日本語メッセージ + **exit 1**（Task Scheduler の Last Result で気づける）
- **GSC は確定週のみ使用**: last_confirmed_week() を新設。実行日との差が min_lag_days（既定3）未満なら
  前週に遡る。前週比も確定週同士。GA4 と GSC で**別々の週窓**を持ち、ダイジェストに
  「GSC確定週: M/D〜M/D（検索データは数日遅れで確定するため、GA4の週とはズレます）」と明記
  ※ dataState は**指定していません**（省略時の既定が final = 確定データのみ。公式仕様で確認済み）
- **query×page** を追加（複合次元、rowLimit 200）。生JSONに保存、本文に上位3行
- 分類の純粋関数: ページ種別（home/store/area/stores/blog/report/closed/other）、指名判定、
  順位帯（1-3/4-10/11-20/21+）
- **有効検索クリック**: 現役 indexable ページ（home/store/area/stores/blog）へのクリック合計。
  noindex レポートと閉店410を除外。本文に「有効クリック: N（全クリック M）」

**実データで発見した追加バグ**: 指名判定が「めぐりび」「meguribi」のみで、
**ブランド表記由来の "megribi" 綴りが「一般検索」に分類**されていました。実CLI smoke で気づき修正済み。

### 2-5. read-only 最新分析CLI（要件A）

新規 scripts/analytics_report.py（514行）。週報から**純粋関数を import して再利用**（コピペなし）。

    python scripts/analytics_report.py --mode latest --days 28 --compare previous --format markdown

- argparse・--help・--mode latest|range・--days 7|28|90・--start/--end・--compare previous・
  --format json|markdown・--as-of
- **完全 read-only**: Supabase保存・LINE送信・ファイル書き込みの機能を**そもそも実装していません**
  （--publish 系のフラグを作らないことで、誤用の余地を消しました）
- GA4: 直近2日を provisional として明示、as_of_jst を出力
- GSC: dataState="all" で取得し、メタデータから available_through / provisional_dates を算出。
  取れない場合は規約ベース（実行日-3日）でフォールバック。**未提供日を0件と表示しません**（「未確定」と出す）
- 終了コード: **0=全成功 / 3=一部取得失敗 / 1=致命的**

**実認証での read-only smoke 実行済み**（2026-08-26）:
exit=0 / 秘密値の漏出なし（ya29. / AIza / Bearer / private_key / G- のパターン検出ゼロ）/
「確定済み: 〜2026-08-23」「未確定の可能性がある日: 2026-08-24, 08-25, 08-26」を正しく表示。

### 2-6. runbook と docs（要件B）

- **docs/ANALYTICS_AGENT_RUNBOOK.md（SSOT）**: 「最新のアクセスを分析して」と言われたときの
  Claude/Codex 共通手順。read-only コマンド / 数字の読み方（当日値は速報・GSCは3日遅れ・
  失敗を0と読まない・有効クリックの定義・28日ローリング優先・母数100未満は判断保留・
  SEO観測期間 2026-08-24〜9/20）/ 禁止事項 / **ブラウザ版ChatGPT単体は対象外**の明記
- **AGENTS.md（root・11行）**: CLAUDE.md と runbook への参照のみ。内容の重複コピーなし
  ※ frontend/AGENTS.md は Next.js 16.3 が next dev のたびに自動生成する別物です（今回コミット対象に含めました）
- **docs/GA4_ADMIN_CHECKLIST.md**: オーナー向け任意3項目（拡張計測の「履歴に基づくページビュー」OFF確認 /
  カスタムディメンション登録 / 保持期間）。各5分と明記
- **docs/ANALYTICS_SETUP.md**: SYSTEM 実行の記述を実態（ahos1/Interactive only）に修正。
  SYSTEM化したい場合の schtasks コマンドを**実行せず**記載
- CLAUDE.md 5章/7章 と plan/RUNBOOK.md から配線（RUNBOOK に analytics-weekly が**一行も無かった**欠落を是正）

---

## 3. やらなかったこと と その理由

**判断基準**: このサイトの実利用は直近28日で36〜37ユーザー、イベント発火は store_view が90日で211件
（≒2.3件/日）。運営は非エンジニアのソロです。**計測の正確さは価値がある一方、分析の粒度を増やしても
読む人がいない**という前提で仕分けました。

| 見送った項目 | 理由 |
|---|---|
| **KPI 8分類の体系化** | 8カテゴリのKPIフレームワークは、運用コストが計測対象の規模を上回ります。既存の週次ダイジェスト（前週比つき）で意思決定には十分です |
| **IntersectionObserver ベースの露出計測群**（decision_card_view 等） | 既存イベントすら週報が拾えていない状態（4/8種が欠落）でした。**まずそれを直すのが先**です。露出イベントを増やしても読まれない情報が積み上がるだけです。リポジトリに IntersectionObserver の使用は現状ゼロで、新規の計測パターン導入はソロ運用の保守負担になります |
| **report_engaged / report_complete** | 同上。まず report_view の名前を実態に合わせました。滞在時間・スクロール到達の計測は、レポート閲覧が90日で19件という母数では判断に使えません |
| **流入UTM分析の強化** | 現在UTMは**アウトバウンド**（予約リンク先への付与）にのみ使われています。インバウンドUTMが価値を持つのは広告・提携送客等の能動的キャンペーンを打つときで、現状そうした施策はありません。**今作っても使い道が無いまま複雑性だけ増えます**。命名規約は runbook に記載済みなので、施策を打つときに即使えます |
| **公式SDK（google-analytics-data 等）への移行** | 現行は意図的に最小依存（google-auth のみ + 生REST）で、fetch_metrics は呼び出しを注入する設計のためテストがネットワーク非依存です。SDK移行は依存追加・認証コード書き直しのコストに対し、**機能面の実利益がありません**（バグではなく様式の好み） |
| **週報の全面二層化** | fetch_metrics は既に層2相当のデータをフル取得し、**Supabase private Storage に生JSONを保存済み**です。新規取得は不要で、必要なら既存JSONを読めば済みます。「オーナーが見る新しい画面」を作るのは機能追加封印方針と衝突します |
| **A/Bテスト** | あなた自身が「現在の母数では提案しない」と書いており、同意します |

---

## 4. データの連続性に関する重要な注意

**2026-08-26 を境に PV の定義が変わりました。**

- 従来: 店舗ページは主要流入経路すべてで2重計上 + レポート検索の1文字ごとに加算
- 今後: ページ移動1回につき1PV

したがって **8/26 以前と以後の PV を直接比較できません**（過去が水増しで過大）。
ユーザー数・セッション数には影響ありません。SEOクリーン観測期間（2026-08-24〜9/20）の
PV 解釈時に、この不連続を必ず考慮してください。

---

## 5. テストと検証の結果

| 種別 | 結果 |
|---|---|
| pytest（全体） | 全緑（新規: test_analytics_report.py 23件 / test_analytics_weekly_report.py +23件、**すべて合成fixture**） |
| vitest | **836 passed**（新規: shouldSendPageView 4 / SSOT網羅 / 送客2イベント6） |
| Playwright e2e | **42 passed** |
| npx tsc --noEmit | エラーなし |
| npm run build | 成功 |
| npm run lint | 0 errors（9 warnings は全て変更前から存在） |
| 実認証 read-only smoke | exit=0・秘密値漏出なし・確定日/未確定日を正しく表示 |

**実データ・実検索クエリは git 管理下に一切コミットしていません。**
テスト fixture は全て合成データです。

---

## 6. 観測待ち（作業ではなくデータ蓄積）

    実装: 完了（2026-08-26）
    計測開始: 2026-08-26（送客イベント・store_slug 統一・PV正確化）
    評価条件: 各主要UIで有効露出100件以上、または28日経過
    最短評価可能日: 2026-09-23 前後
    理由: コーディング時間ではなく、母数の蓄積が必要なため

    SEO観測: 2026-08-24 開始（クリーン28日コホート）
    最短評価可能日: 2026-09-20 前後
    理由: Search Console の反映遅延 + SEO変更後の観測期間

---

## 7. オーナー側で必要な操作（コードでは完了しないもの）

1. **GA4管理画面**（docs/GA4_ADMIN_CHECKLIST.md・各5分・任意）
   - 拡張計測の「ブラウザの履歴イベントに基づくページビュー」が ON だと、手動送信と二重計上になる可能性
   - カスタムディメンション登録（store_slug / brand / surface / mode）
     — 登録した時点以降のデータのみ反映される点も明記済み
   - 保持期間（14ヶ月）
2. **Task Scheduler**（任意）: 全 MEGRIBI-* タスクが ahos1/Interactive only（SYSTEM は warm-cdn のみ）。
   PC常時ログイン運用なら現状で動作します。SYSTEM化するコマンドは docs に記載済み（未実行）

---

## 8. あなたへの依頼

この報告を読んだうえで、次を **plan/ANALYTICS_REVIEW_ROUND2_FINDINGS.md** に書いてください。

### 8-1. 実装のレビュー

実コードを読んで、以下を判定してください（file:line つきで）。

- frontend/src/components/GoogleAnalytics.tsx — PV送信の判定は正しいか。
  **shouldSendPageView の設計に穴はないか**（例: 同一 pathname への意図的な再訪、
  ブラウザバック、router.refresh() 時の挙動）
- frontend/src/lib/analytics.ts — SSOT の型設計。index signature 方式で
  「union は閉じつつ緩い呼び出しを許す」としましたが、**この妥協は妥当か**。より良い方法はあるか
- scripts/analytics_weekly_report.py — last_confirmed_week() の週選定ロジック。
  **min_lag_days=3 は妥当か**。GSC の実際の確定タイミングに対して過剰/不足ではないか
- scripts/analytics_report.py — dataState="all" のメタデータ解釈、
  終了コードの設計（0/3/1）、GA4 の provisional 判定（直近2日）
- docs/ANALYTICS_AGENT_RUNBOOK.md — あなたが実際にこの手順で分析できるか。
  **足りない指示は何か**

### 8-2. 見送り判断への反論

3章 の7項目について、**「それでもやるべき」というものがあれば、理由とともに**書いてください。
その際は次を明示してください。

- なぜ 36ユーザー/28日の規模でも必要なのか
- 実装コストと、それによって**変わる意思決定**は具体的に何か
- 先に消化すべき他の項目（予測の測定契約など）より優先すべき理由

**「ベストプラクティスだから」は理由になりません。** このサイトで何が変わるかを書いてください。

### 8-3. さらなる改良点・追加項目

実装を読んだうえで、**この規模のサイトで実際に効く改善**があれば提案してください。
ただし次の制約内で:

- 新規の有料サービス不可（Render 月7ドル + Vercel Free + Supabase Free）
- ソロ非エンジニア運用（毎日の手作業が増える案は続きません）
- 新機能追加は当面封印（計測・信頼性の改善は歓迎）
- 予測の「測定契約」（ブレンド前の純ML成分を別保存して公平に採点する）が
  ロードマップの次の本命で、これと競合しない範囲

### 8-4. 特に見てほしい懸念

こちらで気になっているが未解決の点です。意見をください。

1. **PV定義の不連続**（4章）をどう扱うべきか。過去データに注記を残す以外にできることは？
2. **?store= 削除の影響**: 内部リンク（StoreCard.tsx 等）には ?store= が残っています
   （リンク先で読まれないだけ）。これらも消して正規URLに統一すべきか、実害が無いので放置でよいか
3. **有効検索クリックの定義**: 「現役 indexable ページへのクリック」としましたが、
   /blog を含めるのは妥当か。/reports/*（noindex）を除外した結果、
   過去90日の83クリックのうち約54件が「有効」になります。この定義で意思決定してよいか
4. **"megribi" 綴りの発見**のように、**分類ロジックに他の見落としが無いか**
   （ページ種別・順位帯・指名判定）

### 8-5. 回答時のルール（前回までと同じ）

- 読み取り専用。ソースコード・設定・ワークフローを書き換えない
  （例外: plan/ANALYTICS_REVIEW_ROUND2_FINDINGS.md の作成のみ）
- git commit / push をしない
- .env / .env.local / secrets/ の中身を開かない・出力しない
- 実測値・検索クエリを公開Git管理ファイルに書かない
- argparse を持たないスクリプト（scripts/score_forecasts.py, scripts/snapshot_forecasts.py）と
  scripts/train_ml_model.py を実行しない
- 分析目的で read-only コマンドを実行するのは歓迎
  （python scripts/analytics_report.py --mode latest --days 28 --compare previous --format markdown）

---

## 9. 制約の確認

- 秘密値（.env / .env.local / secrets/ga-service-account.json）の中身は**一切開いていません**（存在確認のみ）
- 実測値・検索クエリを**公開Git管理ファイルにコミットしていません**
- 実データ確認は read-only モードのみ。LINE送信・Supabase書き込み・ファイル書き込みは発生していません
- Task Scheduler の**変更はしていません**（読み取り schtasks /query のみ）
- テスト fixture は合成データのみ
