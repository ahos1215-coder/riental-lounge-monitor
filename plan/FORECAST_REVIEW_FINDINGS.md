# めぐりび 予測レビュー（2026-08-22）

検証は読み取り専用の静的追跡（`Get-Content` / `rg`）と公開APIへのGETだけで行った。Python import・pytest・禁止スクリプト・外部POST・git操作は実行せず、秘密ファイル／秘密値も開いていない。公開GETは合計100件以内である。2026-08-22の再取得時点では、`/api/forecast_accuracy` は `updated_at=2026-08-22T06:35:47+09:00`、7日MAE 13.39、30日MAE 10.52、baseline 7日MAE 23.84、`nights_count=41`、最新42店舗だった。依頼書の値はその一つ前の更新であり、以下では再取得値を使う。

## 第1部: 3行の結論

1. 現在の予測は「今夜の方向感を見る参考値」にはなるが、13.39人・39/42店勝利・直近41夜という精度根拠は、比較slotと有効夜数が揃っていないため、まだ信用してよい段階ではない。
2. 最初にすべきことは、新しいモデルへの変更ではなく、誤った重み自動更新を凍結し、ML成分・baseline・配信値を同じ夜・同じslotで保存して採点すること。
3. その次は、18:10全夜予測と学習時の情報時点を一致させ、同一期間のChampion/Challenger、夜単位のv2比較、校正済み参考帯へ進むこと。

## 第2部: (a)〜(h) の再判定

| 論点 | 再判定・深刻度 | 結論、反証、隠れていた問題 | file:line / 実際の確認方法 |
|---|---|---|---|
| (a) 自己参照 | **INCOMPLETE / 高** | 自己参照は確認した。しかも入力は純MLでなく、sparse fallback、anchor、旧weightでのblend、late clampまで通った最終配信値である。一方snapshotにはその最終値しか残らない。従って翌朝の`ml_err`は「ML誤差」ではない。また、M=10・B=2から0.167をMAE最適weightとは決められない。残差の符号と相関が必要で、0.309も特定の同符号近似でだけ成立する。 | `oriental/ml/forecast_service.py:160-188,292-310`、`scripts/snapshot_forecasts.py:310-326`、`scripts/score_forecasts.py:398-439,752-799`を静的に系列追跡。公開42店GETでは当日weightは0.472〜0.711（平均0.598、端点0件）で、前日の狭い分布自体も固定的な証拠ではなかった。 |
| (b) 7夜・無検定 | **INCOMPLETE / 高** | 最大7夜・毎夜更新・CIなしは確認した。さらに「7夜」は店別の有効7夜ではない。`_uncontaminated_recent`はmetric nullや0店舗の夜を候補として数え、店別値だけ後でskipするため、実効nは7未満でもpayloadの`nights_used`は7になり得る。EMAだけでは証拠不足を解消しない。 | `scripts/score_forecasts.py:213-226,378-439,922-947`を静的確認。`confidence_interval|p_value|bootstrap|scipy.stats`をコード・テストで`rg`し実装0件を確認。 |
| (c) 40夜の水増し | **INCOMPLETE / 高** | 空夜をsummaryへ入れられる実装は確認したが、非公開の生summaryを開いていないため、実際に何件混入したかは断定しない。より悪い点は、APIが「まず先頭7/30 raw行を切り、その後numericだけ平均」しつつ、`nights_count`はraw行数を返すこと。最新1夜の店舗別MAEを、UIが全`nights_count`夜の値のように表示する経路もある。さらに`live_mae`は18:10開店前予測であり、開店後ユーザーが見るanchor済み予測の精度ではない。 | `scripts/score_forecasts.py:586-620,873-964`、`oriental/routes/forecast_accuracy.py:160-188`、`frontend/src/components/ForecastAccuracyCard.tsx:118-168`、`frontend/src/lib/forecastAccuracy.ts:28-41`を静的確認。公開GETで`nights_count=41`だが各平均の有効nが非公開であることを確認。 |
| (d) baseline | **OVERSTATED / 中〜高** | 7日前1夜baselineはノイズが大きい候補だが、「既存v2は直近6夜同タイプのslot中央値」という説明は違う。v2のshapeは56/84日窓の正規化曲線中央値、scaleだけ直近6有効夜の合計中央値で、実運用candidateはさらにglobal LightGBM scaleと50:50である。特殊期間も参照集合から除外する。従って「既にある強い非ML baselineへ置換」は未実装で、優位も未証明。加えて現行Aは全matched slot、baselineは7日前値があるsubsetだけで採点し、39/42店勝利はpaired比較でない。 | `oriental/ml/postprocess.py:234-297`、`scripts/score_forecasts.py:734-799`、`scripts/build_templates.py:225-289,488-562`、`scripts/snapshot_forecasts.py:273-293`を静的確認。公開shibuya再取得は40予測点に対し`blended_slots=23`で、支持集合差が本番経路に存在した。 |
| (e) 180日窓 | **OVERSTATED / 中** | 2026-08-22の180日前は2026-02-23なので、GW 2026は窓内である。「年末年始・GWが一度も入らない」は誤り。年末年始2025/26は窓外、お盆は窓内だが欠測事故と重なるため、年周期の弱さは残る。祝日長・位置・曜日・月から部分的な汎化は可能なので「実例がなければ一切汎化不能」も強すぎる。 | `scripts/train_ml_model.py:156-188,216-243`、`.github/workflows/train-ml-model.yml:84-115`、`oriental/ml/holiday_calendar.py:1-20,31-60,92-114`、`oriental/ml/preprocess.py:40-46,250-274`を静的確認し日付を計算。Repository Variableによる実効日数上書きは公開情報だけでは未確認。 |
| (f) 対称損失・点予測 | **INCOMPLETE / 中〜高** | 実scheduled workflowは`ML_OBJECTIVE`をenvへ渡しておらず、コード既定の`regression`（L2）である。管理画面に同名Variableがあっても現在のworkflowからは参照されない。「regression/poisson/tweedieは全て対称」は誤りで、Poisson/TweedieはL2と異なる尤度。ただしHPO・gate・公開評価は対称MAE/RMSEで、利用者効用を測っていない本質は正しい。さらにサイトは「空いている時間」と「女性数・女性比・増加中で選ぶ入りどき」という別目的を併存させており、どちらの過大／過小を重くするか未定義である。 | `.github/workflows/train-ml-model.yml:78-134`、`scripts/train_ml_model.py:78-98,167-170,313-344,513-522,667-671`、`frontend/src/components/home/HomeHero.tsx:29-38`、`frontend/src/lib/pricing/recommendEntryTime.ts:190-245`を静的確認。[LightGBM公式objective一覧](https://lightgbm.readthedocs.io/en/latest/Parameters.html#objective)とも照合。 |
| (g) next_morning_rain | **OVERSTATED / 低** | 学習時に翌朝の実測雨を使い、19〜05時の推論時は0になる潜在リーク経路は実在する。しかし公開metadataでは42店×男女=84本すべてのproduction split importanceが0だった。従って現行配信への寄与は0で、holdout +36.7%の主因だった可能性は低い。production refitとholdout evaluatorは別モデルなので、寄与の厳密な上限は同一split ablationなしには断定しない。 | `oriental/ml/preprocess.py:23,128-153`、`oriental/ml/forecast_service.py:378-429`、`scripts/train_ml_model.py:458-475,985-989`を静的確認。公開`/api/forecast_accuracy`で84値=0、公開`/api/range`を3店舗各1000行GETしてJST06〜09時レコード0件を確認。 |
| (h) 店舗別84モデル | **INCOMPLETE / 中〜高** | 独立84モデル・store poolingなしは確認した。ただしfallbackは説明より粗い。直近8日の`total>0`全行を時刻別平均し、曜日・祝日・夜タイプ・天気を無視する。またfallbackはholdout評価に入らず、公開holdout成績は利用者が見る経路を評価していない。poolingは有望だが、それだけでfallback不要になる保証はない。 | `scripts/train_ml_model.py:1067-1096`、`oriental/ml/model_xgb.py:15-46`、`oriental/ml/forecast_service.py:20-39,71-84,313-376`、学習評価`scripts/train_ml_model.py:546-605`との経路差を静的確認。 |

### 棚卸し外で最も重要だった問題: 予測時点の不一致

学習行の`total_slope_30min`は、各target時刻について実測の`t-1 - t-7`を作る（`oriental/ml/preprocess.py:210-228`）。つまり23:00のholdout予測は22:55までの実測変化を知っている。一方18:10の本番は全40未来行を一度に作り、取得時点で最後に得られた1個のslopeを未来全体へforward-fillする（`oriental/ml/forecast_service.py:378-429`）。これは「同じ列名」でも情報時点が違う。

公開metadataでは`next_morning_rain`が84/84モデルで重要度0なのに対し、`total_slope_30min`は84/84で非zero、split importance構成比の中央値8.84%、最大17.42%だった。重要度は因果寄与ではないが、現在のholdout/live乖離を調べる優先度は雨特徴より明らかに高い。以前直した「当行total参照リーク」とは別の、**one-step評価対full-night予測のhorizon mismatch**である。

### 現在の公開数値をどう扱うか

- **7日MAE 13.39 / 30日MAE 10.52:** 算術値は取得できるが、有効夜n・slot coverage・calendar spanがないため「直近7/30夜の精度」としては未監査。
- **baseline 23.84 / 39店前後が勝利:** Aとbaselineのslot支持集合が異なるため、モデル比較・weight決定の根拠として無効。
- **holdout +36.7%:** 3分割自体は改善済みだが、18:10 full-nightとは情報時点が違い、production fallback/anchor/blend/clampも含まないため、本番精度ではない。
- **`live_mae`:** 名称が不正確。実体は「18:10 pre-open served forecast MAE」であり、開店後の利用者体験を表さない。

## 第3部: V1〜V11 への回答

### V1. 自己参照を断てるか、移行と数理

**結論:** ブレンド前系列を保存するだけでなく、重み計算がその系列だけを読むこと、baselineと同一slotで採点すること、旧`live_mae`を入力できないschema guardまで入れれば断てる。確信度は「実コードで確認＋数理的に導出」。

保存すべき「ML側」はraw LightGBMだけでは足りない。利用者へ入る分岐に合わせ、最低でも次を同じsnapshotへadditiveに保存する。

- `raw_model_pred`: 純LightGBM。モデル診断用。
- `preblend_component_pred`: `_sparse_store_fallback`と、そのcapture時点で適用可能なanchor後、baseline blend前。weight最適化はこちらを使う。
- `baseline_pred`と`baseline_version`: 7日前方式、robust candidateなどを別名で保持。
- `served_preclamp_pred` / `served_postclamp_pred`、各slotの`w_ml`、`blend_applied`、clamp再現に必要なcap。
- `captured_at`、`as_of_label`、`schema_version`、`generation_id`。

変更箇所は`oriental/ml/forecast_service.py:160-188,292-310`で内部成分を返せる診断構造を作り、`oriental/routes/forecast.py:82-90`では通常利用者レスポンスを変えずsnapshot用にだけ許可し、`scripts/snapshot_forecasts.py:310-326`へ保存、`scripts/score_forecasts.py:752-799`で共通slotの符号付き残差を保存する。`scripts/score_forecasts.py:398-439`は`preblend_component_mae`以外をweight入力として拒否する。

移行時は**現在のweightをそのまま`legacy_frozen`として凍結**し、0.5へ一律resetしない。旧snapshotから成分は復元不能なので、新schemaの14有効夜まではfleet/brand候補もshadow、店別weightは原則28有効夜まで凍結する。新店・weight欠損だけ0.5を初期値にする。

数理上、M=E|e_M|、B=E|e_B|だけでは

`L(w)=E|w e_M + (1-w)e_B|`

を決められない。同符号で打消しがない近似なら`L(w)=wM+(1-w)B`となり、現行再帰の固定点は

`(M-B)w² + 2Bw - B = 0`

で、M=10、B=2なら約0.309になる。しかし同符号なら真のMAE最適値は、良いbaselineへ全振りするw=0である。逆符号の定数誤差`e_M=+10, e_B=-2`なら真の最適は打消し点w=1/6、現行再帰の固定点は約0.408になる。従って0.309も0.167も一般解ではない。解は同一slotの符号付き残差から、`w=0..1`を直接grid探索して求めるべきで、配信安全域`[0.15,0.9]`は選択後に別制約として扱う。

### V2. 「実際に測れた夜数」の定義

**結論:** 指標ごとにvalid predicateを先に適用し、その後に直近N件を取る。過去rawは消さず、新schema summaryを再構築する。確信度は「実コードで確認」。

`scripts/score_forecasts.py:586-651`に、少なくとも次を保存する。

- captureが18:10許容範囲内、非汚染、finite MAE。
- `expected_stores`、`scored_stores`、missing slugs。fleet夜は例えば90%以上を必須。
- 各店の`actual_slots`、`served_slots`、`paired_component_baseline_slots`。full-night比較は暫定80%（32/40）を有効条件とし、閾値自体をschema versionへ固定。
- component・baseline・actualが**同じmask**で揃ったか。

`oriental/routes/forecast_accuracy.py:160-188`は`filter → sort → take 7/30 → aggregate`へ変更し、`valid_n`、`calendar_days_examined`、`from/to`、`store_coverage`、`paired_slots`を返す。平均値の名前も`preopen_served_mae_7valid`のように予測時点と母数を含める。最新店舗別値は「昨夜」とし、N夜集計ではないことを`frontend/src/components/ForecastAccuracyCard.tsx:118-168`で明記する。

表示例は「**過去10暦日のうち測定できた7夜（8/12〜8/21、42店中40店以上）**」。不足なら「5有効夜の暫定値」と出す。「直近7夜」だけでは連続暦日か有効7件か分からないため避ける。

過去の`summary.json`は削除・上書きせず監査用に残す。生daily scoreから`summary_v2.json`を決定論的に再構築し、null・0店舗・汚染夜を除外する。31日欠測は欠測のまま残す。旧snapshotにはpreblend成分がないため、新weight学習へは使わず`legacy_unknown`とする。

### V3. baselineを6夜中央値へ替えるか

**結論:** 直ちに置換しない。V1の同じsnapshotへ複数candidateを保存し、同一slotのshadow比較で決める。確信度は「実コードで確認＋方向は条件付き推論」。

現行v2を非ML baselineと呼ぶなら、`scale_blend50`はglobal LightGBMを含むため使えない。候補は明示的に次の2本にする。

1. 過去6有効・同night-typeの**slot別中央値**。
2. 現行v2の`shape × scale_ref`。`scale_lgbm / scale_blend50`はbaselineから除く。

`scripts/build_templates.py:234-289,541-562`でcandidateを別versionとして出し、`scripts/snapshot_forecasts.py:273-326`へ旧7日前方式と併記、`scripts/score_forecasts.py:752-844`でA・旧baseline・candidateを完全に同じstore×slot maskで採点する。特殊期間は現行referenceから除外されるため、その夜は「同種特殊期間」または7日前への明示fallbackが必要。baseline versionが変わった夜を同じweight窓へ混ぜない。

現行の逆誤差式だけならBが下がると`w=B/(M+B)`も下がり、ML weightは下がる。しかし直接MAE最適化では誤差相関と打消しが効くため、実際の方向は未確定である。

### V4. 重み更新の統計設計

**結論:** 7候補夜・実効n不明の毎夜更新は正当化できない。候補は週次算出しても、production昇格はforward shadowで判定する。EMAは最後の変化量制御にだけ使う。確信度は「実装確認＋統計設計」。

実装案は次のとおり。

1. `scripts/score_forecasts.py:398-439`で、直近28有効夜（最大calendar age 56日）の共通slot残差に対し、`w=0.15,0.20,...,0.90`を直接評価する。14夜未満は凍結、14〜27夜はbrand/globalへ収縮、28夜以上で店別candidateを許可する。
2. 1夜を1 blockとする。42店舗×40slotを独立な1,680標本とは数えない。candidate選択と検定を同じ28夜で行うと選択バイアスが出るため、過去28夜でcandidateを選び、次の7〜14夜は配信を変えずshadow採点する。
3. incumbentとの差を夜単位でpaired化し、night-block bootstrap 1,000回で95% CIを作る。SciPy既存依存の[`scipy.stats.bootstrap`公式仕様](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.bootstrap.html)を使える。CI上端<0かつ事前に決めた最小効果（暫定0.5人）を超え、繁忙夜で事前non-inferiority marginを破らないときだけ昇格する。
4. 更新は週1回、`w_new=.75*w_old+.25*w_target`、週±0.05上限。これは証拠の代わりでなく、昇格後の急変防止である。`n_valid`、評価期間、CI、baseline/scoring version、candidate/incumbentをweight artifactへ保存する。

14/28は万能な統計保証ではなく、現状7夜から安全側へ移る運用下限である。pilotの夜別差の分散が蓄積したら必要nを再計算する。

### V5. 180日＋過去の同一特殊期間

**結論:** 方向は良いが、測定・時点整合・gate修正より後のP2。次の年末年始に間に合うよう、遅くとも11月までに実装する。確信度は「日付と実コードで確認、効果量は推測」。

`scripts/train_ml_model.py:216-243`の通常180日queryとは別に、`oriental/ml/holiday_calendar.py`が返す`new_year / gw / obon`の直近1〜2回だけを追加queryする。`id`または`(store_id,ts)`で重複排除し、通常窓の`train_limit`とは別上限を持たせる。`_sample_weights`では古い特殊日を永久に等倍で累積せず、店舗×夜で行数を正規化したうえで、特殊夜のweight候補（例0.25/0.5/1.0）をrolling-originで選ぶ。metadataへ種類別の夜数・行数・期間を保存する。

評価は行単位ランダム分割でなく、特殊block全体をholdoutする。同じGWをtrain/test双方へ分割してはいけない。年末年始は過去1回しかないため、その1回への適合で「年末年始に効く」とは証明できず、次回はshadowで答え合わせする。お盆欠測を0として補完・学習することもしない。

副作用は、1年限りの異常イベントへの過適合、古いイベントの行数で見かけの母数が増えること、取得時間・メモリ増加である。これを避ければハイブリッド窓は妥当である。

### V6. Champion/Challenger gate

**結論:** 現行gateは期間難易度とモデル差を混ぜており、10店却下の妥当性は判定不能。同じtestへ現在のproduction artifactを直接当てる修正もリークになる。確信度は「実コードで確認」。

challengerは今回の最新15%を評価する一方（`scripts/train_ml_model.py:382-413,546-605`）、championは過去metadataに残った別期間のMAEである（`scripts/train_ml_model.py:1108-1119`）。単一scalarを比較する`_gate_decision`（`:662-685`）では期間差を除けない。

さらにproduction modelは前回のtrain+val+test全件でrefitされる（`scripts/train_ml_model.py:458-465`）。これを今回testへ当てると、日次rolling窓が重なるためtestの多くを既に学習済みで、championだけが有利になる。

最小のpaired修正は「artifact」ではなく「学習recipe」を比較すること。

1. 週次HPO時、旧championの保存paramsと新challenger paramsを、**今回の同じtrain**でfitし、同じvalでearly stopする。
2. 両evaluatorを同じtest行へ出し、店舗×営業夜のpaired MAE差で比較する。slot行を独立標本にしない。
3. 勝ったparamsだけをfull dataで1回refitしproduction artifactにする。評価期間、両MAE、夜別差、params versionをmetadataへ保存する。
4. 日次runは旧週次paramsを再利用しておりrecipe challengerがない。期間違いgateは外し、non-finite・schema/artifact不整合・同一期間seasonal-naiveへの壊滅的悪化だけをblockしてrefreshする。

週次の追加fitは男女×店舗でほぼ1組増えるが、30 trial Optunaより小さく、GPU不要。真の配信artifact同士を比較したい場合はcandidateを非配信prefixへ置き、両者にとって未見の将来7〜14夜をshadow採点してから昇格する必要があり、これはより正しいが反映が遅れる。

### V7. v2との実験設計

**結論:** 7勝1敗の両側exact sign test p=0.0703125は正しい。しかし「20〜25夜で方向、40夜で大きさ」は、分散・H夜数・停止規則がない現状では統計設計ではなく目安にすぎない。確信度は「数理的に確認＋実コードで支持集合を確認」。

一次単位は42店舗でも1,680 slotでもなく**夜**とする。同じ夜の店舗は曜日、天候、イベント、収集障害を共有するためである。各夜について完全に同じstore×slot集合上で

`D_n = macro_store_MAE(v2) - macro_store_MAE(A)`

を1個作る。負ならv2が良い。現行`scripts/score_forecasts.py:752-844,866-872`はAとv2を別loop・別対象集合でfleet平均するため、先にcommon-support化が必要である。

事前計画は次のようにする。

- 一次指標: 夜別・店舗等weightのpaired MAE差。方向はexact sign test、量はnight-cluster bootstrap CI。
- 繁忙Hを共同一次指標にするなら、overallとHへalphaを事前配分する。L/Mや店舗規模別を多数検定する場合はHolm補正、または探索的CIだけにする。
- H/L/Mは予測対象夜の実測人数で後付けせず、calendar/night typeなど事前情報で固定する。店舗規模層も実験開始前の過去中央値で固定する。
- 現在の8夜は結果を繰り返し見ているためpilot扱いにし、測定修正後の新しい期間をconfirmatoryとする。
- 運用下限は総計28有効夜かつH 12夜。これはpower保証ではなく、pilotの`D_n`分散から最終nを再計算するための最低条件。現在H=3では決着不能で、40夜あってもHが少なければ繁忙夜の結論は出ない。
- 昇格条件は事前固定する。例えばoverallの95% CI上端<0、実務最小差を超える、かつHでnon-inferiorityを破らない。2.1%だけを理由に切替えない。

### V8. next_morning_rain

**結論:** 次のschema更新で除去する。ただし目的は精度改善でなく、死んだ特徴と潜在リークの衛生修正。+36.7%乖離の主因とは見積もらない。確信度は「現行production重要度は実測、holdout寄与は未測定」。

厳密には同一rows、同一train/val/test、同一seed、同一HPO params・roundで、有／無モデルの店舗×夜paired MAEを比較する。importance差でなく誤差差を見る。過去の「天気train/serveずれ77.8%」は天気経路全体の分析であり、この1特徴へ帰属できない。

実装は`oriental/ml/preprocess.py:9-38,128-153`から列と生成を外し、`oriental/config.py:120-121`、`.github/workflows/train-ml-model.yml:108-112`のmodel schemaを同時に上げ、84本を一括再学習する。`oriental/ml/model_registry.py:564-575`は列順を厳密照合するため、GHA/Renderのschema同期を一つのreleaseにする。これ単独を緊急releaseせず、後述の`total_slope_30min`時点整合と同じablation batchに入れる。

### V9. 店舗間pooling

**結論:** LightGBM・CPUで実行可能で、低データ店には有望。ただしpure pooledへ一括置換せず、ブランド別pooled＋localへの収縮をshadowで検証する。fallbackが本質的に不要になる保証はない。確信度は「実装可能性は高、改善量は未測定」。

既に`scripts/experiments/global_vs_per_store.py:1-34,124-216`に`store_id` categoricalを持つglobal対localの土台がある。今回は秘密envの自動読込を避けるため実行していない。LightGBMはCPUでcategorical splitを直接扱える（[公式categorical feature説明](https://lightgbm.readthedocs.io/en/latest/Advanced-Topics.html#categorical-feature-support)）。

最初の実装は全店男女2本より、**ブランド別4本**（Oriental男女、相席屋男女）が安全である。相席屋は割合から人数を逆算する別品質targetなので混ぜない。

- `oriental/ml/preprocess.py`: pooled用に`store_id / area / night_type`を安定category mappingで追加。数値列のmedian fillへ文字列を混ぜない。
- `scripts/train_ml_model.py`: `ML_MODEL_SCOPE=per_store|brand_pooled`を設け、店舗×夜でsample weightを正規化する。大店舗・欠測の少ない店にlossを独占させない。
- 第一候補はrobust baselineからの残差を学ぶpooled model。店ごとのlevel差をbaselineに任せ、共有しやすい曜日・slot・祝日効果を学ぶ。まず既存global実験と並べて評価する。
- `oriental/ml/model_registry.py:328-363,424-433`: 同じpooled artifactをstore別に再parseせず共有cacheする。
- `oriental/ml/forecast_service.py:292-376`: 有効夜が少ない店だけ`pred=alpha*local+(1-alpha)*pooled`とし、`alpha=n/(n+k)`のkをrolling-originで選ぶ。source/alphaをmetadataへ残す。

評価対象はraw local対raw pooledではなく、利用者が見る`local+sparse fallback+anchor+blend+clamp`対pooled全経路である。平均MAEだけでなく、低規模店のworst decile、H夜、brand別を28有効夜以上shadowし、そこを通るまでhard fallbackは残す。副作用はcategory mapping不一致、異常店舗の全体波及、global lossの大店舗偏重、cacheしない場合のメモリ逆効果である。

### V10. 不確実性の帯を本番に出すか

**結論:** 不確実性表示は意思決定に有益だが、現在のv2 p10/p90をAへ足す最小変更は不可。まずA自身の残差で校正し、チャート全面でなく「行く予定時刻／予測peak」に短く出す。確信度は「現行帯のコード欠陥は高、UX効果は推測」。

現在のv2帯には次の問題がある。

- `shape_raw`だけを合計1へ再正規化し、p10/p90は元座標のままなので、`p10 <= shape <= p90`の保証がない（`scripts/build_templates.py:270-275`）。
- `widen_band`はshapeが必ず帯内という前提で、有限・順序・包含をguardしない（`:384-397`）。
- 40slot中12点あれば夜を採用し、未観測slotを0埋めするため、来客変動と欠測patternを混ぜる（`:248-264`）。
- shapeの揺れへ同じscaleを掛けるだけで、夜全体scaleの不確実性がない（`scripts/snapshot_forecasts.py:193-218`）。
- fleet平均coverageだけでkを動かし、帯幅・interval score・H/L別coverageを見ない（`scripts/build_templates.py:400-414`、`scripts/score_forecasts.py:301-374`）。

従ってこれはAの「P10/P90予測区間」ではない。短期の安全化として`0<=low<=point<=high`とfiniteを強制し、名称を`band_low/high`へ変える。その後、Aの共通slotにおける符号付き残差を`scripts/score_forecasts.py:752-844`へ保存し、直近clean nightsの残差分位で

`low=max(0, A+q_low), high=A+q_high`

を作る。sample不足時は`store×night_type → size×night_type → brand/fleet×night_type`へ固定fallbackする。時系列依存下でiid conformalの厳密保証はそのまま主張できないため、rolling night-block backtestでcoverage、平均幅、Winkler/interval scoreを監視する（時系列conformalの論点は[Xu & Xie, ICML 2021](https://proceedings.mlr.press/v139/xu21h.html)）。

本番表示は「22時の予測32人／似た条件での参考範囲20〜45人（直近coverage 81%、n=28）」程度にし、幅が広ければ「今日は読みづらい夜」と伝える。全40点へ濃い帯を常時描くより、利用者の選択点だけへ出す。校正前は内部shadowに留める。

### V11. より良い手法／そもそも何を予測するか

**結論:** 新しいアルゴリズムより先に、予測を「18:10の予定判断」と「開店後の短期nowcast」に分け、各as-of時点で本当に利用可能な特徴だけで学習・採点する。現制約で最も期待値が高い。確信度は「時点ずれは実コードで確認、改善量は未測定」。

現在の1本の40点curveは、二つの別問題を混ぜている。

1. **18:10 planning forecast:** 今夜19〜05時のどこが空く／混むか。現行snapshotが測る対象。
2. **開店後nowcast:** いまの実測を見た利用者に対する次60〜120分。`_anchor_to_tonight`（`oriental/ml/forecast_service.py:510-584`）が変えるが、現行accuracyでは測っていない。

まず`scripts/train_ml_model.py`に「歴史上の各夜を18:10 cutoffとして40未来行を一括生成する」as-of backtestを追加する。pre-open modelでは未来target直前の実測から作る`total_slope_30min`を除去またはcutoff時点の定数へ揃える。`oriental/ml/preprocess.py:210-228`と`forecast_service.py:378-429`が同じfeature builderを使うようにし、one-step holdoutを主要指標から外す。開店後は当面anchorを別policyとして固定し、21時・23時など少数の固定checkpointだけを自動shadow snapshotしてhorizon別に採点する。毎日の目視は不要で、小JSONの追加だけでよい。

予測target自体は男女別人数を残してよいが、評価をMAE一つにしない。

- 「空いている時間」: 店舗相対thresholdを超える確率、過小／過大bias、選んだ時刻と実測最小時刻のregret。
- 「盛り上がる／入りどき」: 推薦ロジックを固定したうえで、予測が選んだ時刻の実測utilityと実測最良utilityのregret。
- curve品質: as-of別30/60/120分MAE、peak時刻誤差、繁忙H夜MAE。
- 安全性: interval coverageと幅、fallback率、clamp率。

利用者行動データがない現時点で、過小予測を何倍重くするかを恣意的に決め、非対称lossへ直行しない。トップの「空いている」と料金cardの「女性が多い」を別modeとして明示し、どちらかをprimary product objectiveに決めてからutility weightを設定する。

制約内の推奨手法は、**horizon-aligned LightGBM + robust baseline residual + 週次direct stacking + night-block residual calibration**である。既存LightGBM、scipy、小JSONだけで実装でき、GPU・新規有料サービス・毎日の手動調整は不要である。

## 第4部: 優先順位つきロードマップ

| 順位 | 効果 × コスト | 実施内容（変更先） | 完了条件 |
|---:|---|---|---|
| 1 | **非常に高 × 1日** | **production weight自動上書きを凍結。** `scripts/score_forecasts.py:922-947`は旧式candidateをshadow pathへだけ書き、現在値を`legacy_frozen`として保持する。0.5へresetしない。 | 翌朝のscoreが成功しても配信weight hashが不変、shadow candidateと理由だけが記録される。予測値はrelease前後で不変。 |
| 2 | **非常に高 × 2〜4日** | V1/V2のmeasurement contract。`forecast_service.py`、`forecast.py`、`snapshot_forecasts.py`、`score_forecasts.py`へraw/preblend/baseline/served、共通slot、valid predicate、versionをadditive保存。`forecast_accuracy.py`とcardを有効n・期間・「18:10」に修正。 | 合成欠測caseでA/baselineのmaskが完全一致。0店/null夜はNへ入らない。旧served MAEからweightを作ろうとするとfail-closed。 |
| 3 | **非常に高 × 2〜4日** | horizon-aligned backtestを作り、pre-openの`total_slope_30min`を除去／cutoff整合。`preprocess.py`と`forecast_service.py`でfeature生成を共通化。`next_morning_rain`は同じschema更新でablation後に削除。 | 歴史夜の23時予測が22:55実測を一切参照しない。as-of feature availability testが通り、旧／新の夜別paired結果が出る。 |
| 4 | **高 × 2〜4日** | V6のpaired recipe gate。週次に旧paramsと新paramsを同一train/val/testで比較し、日次の期間違いgateをsanity-onlyへ。 | metadataに同一test期間・両MAE・夜別差が保存され、旧期間scalarとの比較が0件。 |
| 5 | **高 × 実装2〜3日＋観測待ち** | V4の週次direct stackingをshadow導入。28有効夜でcandidate、次7〜14夜でforward評価、CIと繁忙夜guard後に±0.05以内で昇格。 | weight lineage、n、CI、versionが公開可能。自己参照入力0件。最低14/28夜ruleを満たさない店は凍結／pooled。 |
| 6 | **中〜高 × 設計1日＋観測待ち** | V7のA/v2 protocolを固定。common support、夜単位D、overall/H共同指標、固定checkpoint、confirmatory期間を宣言。 | 総28有効夜かつH12夜、事前停止規則を満たすまで自動で「未決着」。42店を独立nとして扱わない。 |
| 7 | **中 × 2〜3日＋校正待ち** | V10のv2帯不変条件を直し、Aのnight-block residual reference bandをshadow生成。 | 全slotでfiniteかつ`0<=low<=point<=high`。H/L・規模別coverage、幅、interval scoreが蓄積し、表示文言が「参考範囲」。 |
| 8 | **中 × 2〜4日（11月まで）** | V5の180日＋直近同種特殊block query、重複排除、event-block評価、metadataを追加。 | New Year/GW/Obon別の採用夜数が監査でき、通常窓との重複0。特殊blockを行分割していない。 |
| 9 | **中〜高だが不確実 × 5〜8日＋shadow** | V9のブランド別pooled4本とlocal shrinkageを既存experimentから本番全経路shadowへ。 | 28有効夜でfleet平均だけでなく低規模worst decile・H夜が非劣化。共有cacheのRSSが84 local以下。通過までfallback維持。 |

ロードマップ1〜4の間は、モデル切替・v2昇格・weight再最適化をしない。測定契約とas-of整合が変わるたびに過去スコアとの連続性が切れるため、schema/version境界を明示し、旧値を新しいCIへ混ぜない。

## 第5部: オーナー向けの一言（3行）

いまの予測が全く無価値という意味ではありませんが、「何人ずれたか」「baselineより勝ったか」を今の表示どおり信じることはできません。  
まず自動の重み調整を止め、同じ夜・同じ時間帯・同じ予測時点で公平に答え合わせすれば、本当に効いている部分と悪化させている部分が分かります。  
新しいAIを足すより先に測り方を直すことが、最小の費用で予測を本当に当てるための近道です。
