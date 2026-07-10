# 予測 v2（夜シェイプ・テンプレート × スケール）— SHADOW 設計

本番(A) = 店別 LightGBM + 後処理(clamp/blend)は、実測の答え合わせで季節ナイーブ等の単純
手法に負け続けている（艦隊バイクオフ: v2 MAE 7.89 vs A 11.88）。v2 は検証済みの根本転換
案 =「**店別・夜タイプ別の夜シェイプ × スケール**」。本ドキュメントはその SHADOW 実装
（本番配信を一切変えず、毎晩 A と並べて採点する）の設計と、昇格の判断基準・禁止事項を定める。

関連: `plan/FORECAST_ACCURACY.md`（答え合わせループ本体）, メモリ `forecast-redesign-2026-07-10`。

---

## 1. 予測式

各店・各夜タイプ `type ∈ {L, M, H}` について 40 スロット（19:00〜04:45 JST・15分刻み・
-6h 夜規約）のテンプレートを持つ:

```
total[i] = shape[i] × scale_ref              # i = 0..39
men[i]   = total[i] × men_ratio[i]
women[i] = total[i] − men[i]
band_low[i]  = p10[i] × scale_ref            # 予測帯(下)
band_high[i] = p90[i] × scale_ref            # 予測帯(上)
```

- `shape[40]`: 各夜を「夜合計」で正規化した曲線の per-slot **median**。合計 1.0 に再正規化。
- `p10[40] / p90[40]`: 正規化曲線の per-slot 10/90 百分位（帯・再正規化しない）。
- `men_ratio[40]`: `men/(men+women)` の per-slot median、サンプル無しは 0.5。
- `scale_ref`: **直近 6 夜（同タイプ）の夜合計の median**。今夜の規模。

「夜合計」= 40 スロットの実測総数(占有)の和。`total[i]=shape[i]×scale_ref` で占有曲線を復元。

---

## 2. 夜タイプ（軸は曜日ではない）

139k 行・8 店で実測した夜タイプ別の混雑倍率:

| 夜タイプ | 定義 | 実測倍率 |
|---|---|---|
| 平日通常 | 月〜木・翌日も平日 | **1.00** |
| 日曜(M) | 今日休み・翌日仕事 | **1.20** |
| 金・土(H) | 翌日休み | **3.56** |
| 祝前日(金土以外)(H) | 翌日休み | **3.55**（n=50 夜、金土と実質同一）|

→ 軸は「休前夜構造」= **2 ビット**で決まる（`oriental/ml/night_type.py`）:

```
day_off(x) = (x.weekday() >= 5) or jpholiday.is_holiday(x)   # 土日 or 法定祝日のみ
classify_night(d):
    明日休み(day_off(d+1)) → 'H'   # 金/祝前日/土/連休中日
    今日休み(day_off(d))   → 'M'   # 日曜/連休最終日
    それ以外               → 'L'   # 平日通常
```

検証済みマッピング: 金→H, 土→H, 通常日曜→M, 月〜木→L, 木祝の前日(水)→H,
月祝の前日(日)→H, 木祝→翌金が平日で M, GW 中日→H。

**慣習休業は classify_night に入れない**。お盆/年末年始/GW はイベント異常として
`special_block(d) ∈ {gw, obon, nye}` で別管理し、**テンプレ/スケールの参照集合から
除外**する（汚染ガード）。今夜がたまたま special_block でも v2 は該当タイプのテンプレで
予測し、出力に special_block をタグ付けする。

- obon = 8/13-15、nye = 12/29-1/3、gw = 4/29-5/6 を含む連続休業ブロック。

---

## 3. 参照窓とフォールバック梯子

タイプ別ルックバック窓: **L/H = 直近 8 週(~34 / ~18 夜)、M = 直近 12 週(~12 夜)**。
取得は直近 ~13 週。有効夜 = 観測スロット >= 12 かつ 夜合計 > 0。

梯子（`build_store_templates`）:

- **L**: L 夜 >= 4 → L 直接。不足 → all-type（全取得夜・never empty）。
- **H**: H 夜 >= 4 → H 直接。不足 → all-type。all も無ければ L を流用。
- **M**: M 夜 >= 4 → M 直接。不足 →
  - **L のシェイプ**を借用し、
  - スケールは M 夜 >= 3 なら M 自身の直近6中央値、それ未満は **L スケール × 1.20**
    （実測日曜係数）。
- 店がデータ皆無 → 既存 `templates_v2.json` の当該店エントリを **carry-forward**。前回も
  無ければ警告して omit。最新行が 7 日超古い店(stale)も carry-forward（train と同じ）。

出力 1 本: `forecast/templates_v2.json`（`{schema:'v2t1', generated_at, stores:{id:{L,M,H}}}`）。
各タイプに `shape/p10/p90/men_ratio/scale_ref/n_nights/fallback` を記録。

---

## 4. SHADOW 配線（本番配信は不変）

1. **`scripts/build_templates.py`**（唯一のテンプレ生成コマンド／`build-templates.yml`,
   07:30 JST）: 上記テンプレを生成し Storage に upsert。`--dry-run` でカバレッジのみ表示。
2. **`scripts/snapshot_forecasts.py`**（18:10 JST）: A スナップショットに加え、今夜の
   `type=classify_night(tonight)` のテンプレから v2 予測を組み、同じ JSON の新キー `v2`
   （店別 `{night_type, special_block, data[40], template_generated_at, template_fallback}`）
   に併記。テンプレ欠如/古い(>48h)店は `v2:null`（A は無傷）。
3. **`scripts/score_forecasts.py`**（06:10 JST）: A・v2・baseline を同一スロットマッチング
   で採点。MAE に加えプロダクト・スコアカード:
   - **peak_time_hit30**: 予測ピーク時刻が実測ピークと <=30 分（マッチ >=20 & 実測ピーク
     >=5 人の夜のみ）。
   - **ghost_index**: 深夜(23:00 以降)で実測が実質ゼロ(<= max(1, ピークの5%))のスロットの
     平均予測総数（過剰予測=ゴースト、小さいほど良い）。
   - **band_coverage**（v2 のみ）: p10<=実測<=p90 のスロット割合。
   結果は夜次 scores JSON の `v2` / `scorecard` キーに additive 記録（既存キー・
   `routes/forecast.py _fetch_live_accuracy` は不変）。exit code は従来通り A vs baseline のみ。

---

## 5. Shadow → 昇格プラン（6〜8 週）

1. **W0**: テンプレ初回シード（手動 workflow_dispatch）→ 翌朝から v2 が snapshot/score に載る。
2. **W1-6**: 毎朝 GITHUB_STEP_SUMMARY の「A vs v2 vs baseline」表 + 直近7夜ローリングを観測。
3. **昇格条件（すべて満たすこと）**: 直近 4 週以上のローリングで、艦隊 v2 が
   - MAE で A と baseline の両方に勝つ、かつ
   - peak_hit30 が A 以上・ghost_index が A 以下、かつ
   - band_coverage が概ね 0.8 前後（極端な過大/過小帯でない）。
4. **昇格**: 条件成立後、別 PR で serving を v2 に切替（本ドキュメント更新 + A を段階的に縮退）。
   SHADOW 期間中に serving を触ってはならない。

---

## 6. 禁止事項

- **直近レベル補正（直近数夜比での動的スケール補正）は実装禁止。** イベント夜に MAE 28-34 へ
  自爆することを実測済み（2026-07-09 バイクオフ）。スケールは「同タイプの直近 6 夜の
  median」で固定し、今夜の途中経過や直前夜の比率で動的に補正しない。
- **テンプレ再生成は `scripts/build_templates.py`（=`build-templates.yml`）の 1 コマンド
  以外に生やさない。** 別経路の再生成・手 patch を作らない。冪等・単一・観測可能を保つ。
- SHADOW 期間中は本番配信 (`oriental/ml/forecast_service.py` / routes) を変更しない。
