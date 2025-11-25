# めぐりび / MEGRIBI ROADMAP
最終更新: 2025-11-25  
対象ブランチ: main  

このファイルは現在の進捗と次のステップを簡潔に示します。大枠の構成は維持しつつ、Supabase 一本化 Step1/2 完了を反映しました。

---

## 完了済み（DONE）
- 2025-11-25: Supabase 一本化 Step1/2 完了  
  - 収集: `collect_all_once` で 38 店舗のスクレイピング → Supabase `logs` に挿入可能  
  - /api/range: DATA_BACKEND=supabase で Supabase logs 読み出し（store_id, ts 範囲, limit）、legacy へフォールバック実装済み  
  - 予測: ForecastService が Supabase logs を履歴に利用し、/api/forecast_next_hour / /api/forecast_today が本番 Render で動作確認済み  
  - /api/meta: AppConfig.summary() を返却し、data_backend / supabase / store_id / window / timeout / max_range_limit 等を可視化

---

## 次のステップ（WIP / TODO）
- マルチ店舗 UI / Next.js 側の拡張（複数店舗カード・切替 UI）
- 相席屋 / JIS など他ブランド対応の検討と stores マスタ整理
- Supabase スキーマ/クエリのチューニング（indexes, retention, weatherカラム活用）
- 予測精度向上（特徴量追加、モデル更新、学習スケジュール化）
- 監視・運用整備（/api/meta や /api/range の定期チェック、自動アラート）

---

## 参考
- /api/meta で現在の設定を確認可能（DATA_BACKEND, supabase.url/service_role, store_id, window, timeout など）
- フロントエンドは既存 API (/api/range, /api/forecast_*) を利用するため、Supabase へ切り替え後もエンドポイントは不変
