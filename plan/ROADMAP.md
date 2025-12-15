# ROADMAP
Last updated: YYYY-MM-DD / commit: TODO

## P0 (完了)
- Next.js 最小版動作（フロント: Vercel）、バックエンド: Render/Flask。
- `/api/range` 安定（Supabase `ts.desc` 取得→`ts.asc` 返却、store+limit のみ、max_range_limit=50000、夜フィルタなし）。
- useSearchParams + Suspense 対応、Recharts Tooltip 型拡張でビルド安定。
- 二次会スポット: map-link frontend only（Google Maps 検索リンク）。

## P1（進行中）
- Supabase `logs`/`stores` 導入・移行（GAS 二重書き込み継続しつつ Supabase を優先）。
- UI コンポーネント整理（ダッシュボード最小セットの安定化）。
- Render Starter での cron `/tasks/tick` 運用（5分間隔、38店舗収集、ENABLE_FORECAST トグル）。

## P2（予定）
- マルチ店舗・ブランド化（Oriental / Aisekiya / JIS）とルーティング/メタデータ反映。
- 豪華ダッシュボード化（カード/グラフ/近隣案内の拡充、ただし second venues は map-link 方針維持）。
- 観測・運用強化（cron 可観測性、ログ/メトリクスの拡張）。

## P3（将来）
- NLPベースのクエリや二次会高度化（必要に応じ `/api/second_venues` を軽量レコメンド化）。
- 天気/人気傾向連動の高度推定。
- 追加ストア/ブランドの自動拡張と管理UI。
