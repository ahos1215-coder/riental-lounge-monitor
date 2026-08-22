# 重み凍結の設計突き合わせ — 最終回答（2026-08-22）

今回は既存診断を前提とし、新しい問題探しや精度の再評価は行っていない。静的なコード／workflow確認だけで、Claude案の事故境界、移行、監視、解除条件を詰めた。秘密ファイル・秘密値は開かず、Python/import/pytest、禁止スクリプト、git操作、外部書き込みも実行していない。

## 1. §3 Claude案への批評

結論は、**3-1・3-2・3-6の方向は採用、3-3〜3-5は安全条件を追加して採用**である。凍結時に現在の配信値を変えないという中心案には賛成するが、booleanの解釈、backupの世代、hash不変監視、空candidate、旧runとの競合を補強する必要がある。

| Claude案 | 判定 | 採用してよい点 | 直すべき点と理由 |
|---|---|---|---|
| **3-1 writer分岐** | **修正して採用** | 唯一の配信PUTは`scripts/score_forecasts.py:944-947`なので、凍結中にここへ一切PUTしない設計は単純で検証可能。重み0件でも空canonicalを書いてしまう現行経路（`:948-952`）も止められる。 | `os.environ.get(...,"1").strip()=="1"`は、`true`やtypoをすべて「凍結OFF」にするため不可。未知値はcanonicalを触らずjobを赤にする。legacy candidateは将来の昇格材料ではないので、`publish_eligible:false`と`source_metric:served_live_mae_legacy`を明記し、paired candidateとはpathを分ける。freeze解除時もshadowは常に書き、validな場合だけcanonicalを追加PUTする方が監視をmode非依存にできる。 |
| **3-2 workflow配線** | **採用。ただしmode化を推奨** | `.github/workflows/forecast-accuracy-track.yml:89-112`はenvを明示配線する構造であり、Repository Variable名を書くだけでなくRun stepへ渡すのは必須。 | booleanより`BLEND_WEIGHTS_MODE=frozen|legacy_daily`が安全。未設定は`frozen`、未知値や未実装`weekly`はfail-closed。将来の正常解除先を`weekly`、緊急rollbackだけを`legacy_daily`と区別できる。workflowとPython双方で既定`frozen`を固定し、静的workflow testで「死に設定」化を防ぐ。 |
| **3-3 初回backup** | **目的は採用、固定名＋skipは不可** | canonicalを一切変更せずexact bytesを退避するのは、誤上書き・単一object削除への保険になる。 | 固定backupを「存在したらskip」すると再凍結時に旧世代を使う。`scripts/_supabase_common.py:140-170,200-239`のPUTは常にupsertで、GET→PUTもtransactionではない。`sha256(served_bytes)`をfreeze IDにした世代pathへexact bytesを保存し、read-back hash確認後にmanifestを最後に書く。同じbucketなのでbucket全損・Storage障害の保険ではない、と説明を限定する。 |
| **3-4 監視** | **不足。hash監視へ変更** | canonical存在とshadow鮮度は必要。48時間は長期沈黙を防ぐ最低線として許容できる。 | 「存在」だけでは別内容へ毎晩上書きされても緑。manifest・backup・canonicalのSHA-256一致、JSON妥当性、weight非空／有限、shadowのfreeze IDと48時間鮮度を確認する。score後続stepではscore未発火を検知できないので、独立scheduleから実行する。`forecast_service.py:217-277`はStorage障害時にmemory上の旧値を返せるため、公開予測が動いていることもStorage健全性の代用にならない。 |
| **3-5 テスト3本** | **必須だが不十分** | freeze時PUT先、legacy時PUT先、未設定時freezeの3本は基本契約として必要。既存`tests/test_score_blend_weights.py:95-151`のmock構造を利用できる。 | 追加必須は、未知modeのfail-closed、空candidateでcanonical保持、backup exact bytes/read-back、同世代冪等、再凍結の新世代、canonical hash変化検知、monitor fresh/stale/missing/mismatch、workflow env配線、新店fallback。現在のweight blockは例外を握り潰す（`score_forecasts.py:922-954`）ので、integrity failureが最終return code（`:984-1006`）へ届くtestも要る。 |
| **3-6 時限措置** | **方向は採用、解除契約を数値化** | 測定契約が先、解除後も旧毎晩更新へ戻さず週次方式へ、という順序は正しい。 | `BLEND_WEIGHTS_FREEZE=0`は現行コードでは即「旧毎晩更新」へ戻るため、文言と実装が矛盾する。正常な遷移は`frozen → weekly`とし、`legacy_daily`は緊急時だけ。valid night、最低n、shadow期間、CI、更新幅を今はpolicy v1として文書化し、freeze PRで自動解除は実装しない。 |

### Claude案に無かったcutover上の注意

- workflowは毎朝06:10 JSTで、現在`concurrency`がない（`.github/workflows/forecast-accuracy-track.yml:27-54`）。旧commitで既に開始したrunは新しいfreeze設定を知らずcanonicalを書ける。初回配備は06:10付近と進行中runを避け、workflowへ同一group・`cancel-in-progress:false`を追加する。
- serving側のcache TTLは約1時間（`oriental/ml/forecast_service.py:217-277`）。凍結はcanonicalを変えないので通常影響しないが、復旧や将来の解除が全workerへ見えるまで最大1時間を受入条件に入れる。
- Repository Variable変更だけのrollbackは「次回06:10 runから反映」であり即時ではない。即時反映にはworkflow_dispatchがもう1操作必要、という制約を隠さない。

## 2. Q1〜Q7 への回答

### Q1. 凍結フラグの既定値

**既定は凍結ON。最終案はbooleanでなくmode enumにする。**

- `BLEND_WEIGHTS_MODE`未設定／空は`frozen`。ローカル手動実行でenvを忘れてもcanonicalへ書かない。
- 許可値は当面`frozen`と`legacy_daily`だけ。未知値はshadow／scoreを可能な範囲で残すがcanonical PUTは0、最終exit 1。
- workflowは`BLEND_WEIGHTS_MODE: ${{ vars.BLEND_WEIGHTS_MODE || 'frozen' }}`と明示配線し、Python側も同じ既定を持つ二重防御にする。
- Claude案より良い点は、typoがpublish側へ倒れず、将来の正常な`weekly`と危険な旧`legacy_daily`を混同しないこと。

### Q2. 凍結する値

**(a) 配備直前から存在するcanonicalのexact bytesを、そのまま固定する。**

- (b) は同じ汚染入力の再計算で、根拠は改善せず値だけ変わる。(c) 0.5一律は最大約0.21の即時変更になり、freeze PRを本番実験へ変えてしまう。
- 「初回freeze runで計算したcandidate」を一度canonicalへ書いてから止めるのではない。最初のrunからcanonical PUTは0。
- backup前にJSON、activation時の店舗集合、有限な0〜1値を検証し、hashをfreeze IDにする。現在値が最適だとは主張せず、「挙動を変えず揺れだけ止める」選択である。
- Claude案と結論は同じだが、固定対象をobject bytesとhashで一意にする点が強い。

### Q3. 新店のfallback

**条件付き(c): 正常なnonempty weights内で対象keyだけ無ければ0.5。Storage全体の失敗時は従来どおり1.0。**

- 0.5は現行`blend_weight()`のn=0 prior（`scripts/score_forecasts.py:378-395`）と一致し、汚染されたfleet中央値を新店へ継承しない。
- 新店の最初の約7日は7日前baseline自体が無く、w=0.5でも該当slotはMLのままなので、存在しないbaselineを無理に混ぜない（`oriental/ml/postprocess.py:272-290`）。
- file欠損・取得失敗・空weightsまで0.5へ変えるとStorage障害時の全店挙動を同時変更するため、その場合は現行1.0を維持する。
- Claude案(a)より良い点は、新店がfreeze終了まで恒久純MLになる穴を数行で閉じ、既存42店とStorage障害時の挙動を変えないこと。

### Q4. backup、shadow、監視

**backupは世代付き、shadowはlegacy専用60夜rolling、監視は独立hash検証にする。**

- `accuracy/blend_weights_freeze/generations/<sha256>.json`へexact bytesを置き、再GETでhashを確認後、`accuracy/blend_weights_freeze/current.json`へ`state/freeze_id/activated_at/source_generated_at/backup_path/store_count`を書く。manifestをcommit markerにする。
- shadowは`accuracy/blend_weights_shadow/legacy.json`に`publish_eligible:false`、freeze ID、使用日付、候補weightをnight-date upsertし、既存`SUMMARY_KEEP=60`（`score_forecasts.py:61-65,896-920`）と同じ60件でcapする。freeze中は元の1 PUTの置換なので、通常のwrite回数は増えない。
- 独立`scripts/monitor/check_blend_weights_freeze.py`と専用GHAを6時間ごとに実行し、manifest、backup、canonicalのhash、JSON/値域、shadow 48h鮮度とfreeze IDを検証する。異常は既存`notify-on-failure.yml`へ接続する。
- 自動restoreはしない。`workflow_dispatch --restore`だけがmanifestとbackupを再検証してcanonicalを復元する。同一bucket backupはobject事故用で、bucket障害には効かない。

### Q5. 解除条件を今決めるか

**数値は今policy v1として文書化する。freeze PRには自動解除を入れない。**

- valid store-nightは、非汚染、generation一致、preblend/baseline/served/actualの同一mask、共通32/40 slot以上、finiteを必須とする。
- 測定契約後、active店の80%以上が14 valid nightsへ到達し、直近7日monitor REDなし。新weekly updaterをさらに14 valid nights shadow運転する。
- 店別は`<14`なら現freeze値、`14〜27`ならfleet/brandへ収縮、`>=28`で店別candidateを許可。週1回、1回±0.05。
- 現freeze policyとの夜単位paired差で95% CI上端<0、暫定最小効果0.5人、繁忙夜non-inferiorityを満たす場合だけ昇格する。
- 正常解除はmodeを`frozen → weekly`へ1操作で変更する。`legacy_daily`へ戻すことを解除とは呼ばない。35日でreview warning、56日で継続alertは出すが、期限だけで自動解除しない。

### Q6. 測定契約・schema v8との順序

**weight freeze → 測定契約 → as-of検証 → v8 composite shadow → v8昇格 → v8夜でweight再学習、の順。**

- 同一schema・同一recipeのv7定例refitは短期的に継続可。ただし「予測全体を固定した」とは表現せず、snapshotへmodel generationを残す。
- slope/rainを変えるv8は、`frozen_w×v8+(1-frozen_w)×baseline`の最終配信candidateを、現行v7 compositeと同じstore×slot maskで7〜14 valid nights shadow比較する。生MLだけのoffline改善では出荷しない（blend経路は`oriental/ml/postprocess.py:226-300`）。
- v8はv7と別immutable prefixへ置き、schemaとprefixを一つのrelease pointerで選ぶ。現状の別々の`FORECAST_MODEL_PREFIX` / `FORECAST_MODEL_SCHEMA_VERSION`操作では、cold-start rollback時に不一致が起こり得る（`model_registry.py:564-575`）。
- model昇格とweight解除を同日にしない。v7で貯めた14/28夜はv8用weightへ流用せず、v8 generationの夜を新しく数える。
- Claude案より良い点は、「凍結weightと新モデル」という未評価の組合せを、その組合せ自体で判定してから出すこと。

### Q7. 凍結しない方が良いという反対論

**最強の反対論はあるが、現データでは立証も反証もできない。それでも凍結を推奨する。**

- 旧controllerが大外れMLのweightを翌晩下げ、短期保険として助けた夜はあり得る。freeze時点のweight自体が悪い可能性もある。
- raw preblend系列が保存されていないため、過去にその保険が何人分効いたかというcounterfactualは復元不能。
- 一方、非凍結は不正なsensorで配信を毎晩変え続け、凍結は現在値を変えず、legacy candidateもshadowへ残す可逆措置である。
- したがって「保険が無価値だから止める」ではなく、「効いた可能性は残るが、効果を測れない自動制御を一時停止し、正しいsensorができるまで観測する」が正確な判断である。

## 3. あなたへの最終推奨案一式

以下を**1日PRの単位**とする。モデル、特徴量、weight値そのものは変えない。

### [F-1] writer modeと配信不変条件

- `scripts/score_forecasts.py:922-954`へ`BLEND_WEIGHTS_MODE`を追加。未設定は`frozen`、`legacy_daily`だけを緊急許可、未知値はfail-closed。
- legacy candidateは毎晩計算し、常に`accuracy/blend_weights_shadow/legacy.json`へ60夜rollingで書く。`publish_eligible:false`とsource/versionを必須にする。
- `frozen`では`accuracy/blend_weights.json`へのPUTを常に0回。`legacy_daily`でもcandidateが非空・finite・値域内・期待店舗集合を満たすときだけ、shadowに加えてcanonicalへPUTする。
- config、backup、shadow integrityの失敗を広い`except`で緑にせず、score/summaryを残した後に最終exit 1とする。

### [F-2] workflowとcutover

- `.github/workflows/forecast-accuracy-track.yml:27-112`へmodeを明示配線し、同一concurrency group、`cancel-in-progress:false`を追加する。
- `tests/test_workflow_docs_consistency.py`でenv keyと既定`frozen`を固定する。
- 初回配備は06:10付近を避け、旧runが無いことを確認してから行う。凍結確認はcanonical hash不変。cacheのため復旧／解除の反映には最大1時間を見る。

### [F-3] exact backupとfreeze manifest

- activation時のcanonical bytesを検証し、`freeze_id=sha256(bytes)`とする。
- `accuracy/blend_weights_freeze/generations/<freeze_id>.json`へexact bytesをPUT、read-back hash一致後に`accuracy/blend_weights_freeze/current.json`を最後にcommitする。
- 同じactive freeze IDなら冪等。`legacy_daily`でvalid canonicalのread-backまで成功したらmanifestを`state:inactive`にし、そこからの再凍結は新世代を作る。backup/hash失敗時もcanonicalは一切変更せずjobを失敗させる。
- 復旧は自動で行わず、検証付きworkflow_dispatchだけにする。

### [F-4] 新店fallback

- `oriental/ml/forecast_service.py:217-290`で、正常なnonempty weight mapに対象keyだけ無い場合は0.5。
- map全体が空、file欠損、取得失敗は現行1.0を維持する。Renderへfreeze envを追加せず、GHAとの二重設定を作らない。

### [F-5] 独立monitor

- stdlib＋argparseの`scripts/monitor/check_blend_weights_freeze.py`と独立workflowを追加し、6時間ごとに実行する。
- canonical存在だけでなく、manifest/backup/canonicalのSHA-256、JSON、weight集合・値域、shadow freeze ID・48時間鮮度を確認する。
- 異常時exit 1を既存通知へ接続。restore modeはmanual dispatchだけ、通常scheduleはread-only。

### [F-6] 回帰テスト

- Claude案の3本に加え、unknown mode、empty candidate、exact backup、read-back失敗、冪等、再凍結、canonical改変、shadow dedup/60件cap、monitor stale/missing/hash mismatch、workflow env、新店0.5／Storage失敗1.0を固定する。
- 特に「score成功でもcanonical hash不変」と「integrity異常時はcanonical PUTゼロかつjob RED」を受入条件にする。

### [F-7] 解除policy

- 上記Q5のvalidity、14/28夜、14夜forward shadow、CI、±0.05をpolicy v1として記録し、自動解除はしない。
- 新weekly writer実装後にだけ`frozen → weekly`。`legacy_daily`は緊急rollbackであり、通常解除先ではない。
- 35/56日reminderは「放置検知」であり、時限による自動publishには使わない。

### [F-8] 後続変更との境界

- この1日PRに`preprocess.py`、`train_ml_model.py`、schema v8、84本再学習、weight再計算は含めない。
- 測定契約は次のadditive release。v8は別prefix・composite shadow・単一release pointerが揃うまでproductionへ出さない。
- v8昇格後もweightは凍結したままにし、v8 generationの有効夜を新しく蓄積してからweekly weightへ進む。

## 4. 相違が残る点と、オーナー向け判断材料（3行）

Claude案の「今の値を変えず、毎晩の候補だけshadowへ出す」という本体は、そのまま採用してよいです。  
私の案との違いは、0/1フラグを明示modeへ、固定backupをhash世代へ、存在監視をhash不変監視へ強め、新店だけ0.5 priorにする点です。  
1日で入るなら強化案を選んでください。もし削る場合でも、**fail-closed設定・canonical hash監視・空candidate上書き禁止**の3点は削らないでください。
