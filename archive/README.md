# archive/

使用済み・保管用。削除せず隔離しています。

- `apply_forecast_min.ps1` — 予測ロジック調整の適用に使っていたワンショットスクリプト。役目を終えたためここに退避。
- `shap_analysis.py` — SHAP で特徴量寄与度を見る分析用。XGBoost 時代の `model_{store}_men.json` を読む作りで、2026-04-12 の LightGBM 移行（保存は `.txt`）以降はモデルが見つからず常にスキップになるため退避（旧 `scripts/shap_analysis.py`）。
- `inspect_feature_importance.py` — 特徴量重要度の確認用。XGBoost 専用の `model.get_booster()` を呼ぶため、LightGBM 移行後は常に AttributeError になるため退避（旧 `scripts/inspect_feature_importance.py`）。
- `analyze_nagasaki_performance.py` — 長崎店の予測精度を artifacts/ の学習結果から読む一回性の分析用。優先日付 `20260324` がハードコードされており、artifacts/ 自体が git 追跡外のため通常は動かない（旧 `scripts/analyze_nagasaki_performance.py`）。
- `ablation_ma_test.py` / `ablation_signal_extraction.py` / `delta_direction_nagasaki.py` / `delta_target_nagasaki.py` — 2026-03-24 の ML 2.0 検討で使った Delta/Ablation 実験4本。xgboost・sklearn に直接依存しており、2026-04-12 の LightGBM 移行後の本番特徴量とは前提が異なる。定期実行からの参照は無い（旧 `scripts/experiments/`）。

（`scripts/supabase_test_insert.py` は退避ではなく削除した。実行すると本番 Supabase `logs` に
`ol_nagasaki` の偽データ行を無条件で INSERT する踏み地雷で、参照元もガードも無かったため。）
