# ROADMAP.md — 優先順位つき実装計画

## P0（すぐ着手）
- 複数店舗対応（`STORES_JSON` による収集・API `store` 切替）
- API キャッシュ層（1〜5分）
- OpenAPI 定義の追加（契約の明文化）

## P1（今四半期）
- Postgres/Supabase への保存と過去集計 API
- 異常検知（連続 0 件、取得落差など）と通知
- ヒートマップ/予測の実データ化

## P2（将来/任意）
- LINE 通知（今日の見込み、ピーク予測）
- 認証（API Key）
- Cloudflare 等のエッジキャッシュ

## テスト計画
- `tests/test_range_params.py` … パラメータ正規化（クランプ）・日付逆転 422
- 以降、店舗切替/API 互換テストを追加
