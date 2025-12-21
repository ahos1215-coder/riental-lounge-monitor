# Facts（MEGRIBI Blog）

## 方針（A + Supabase保存の二段構え）
- Supabase: facts_full（完全版・正本・非公開）
- GitHub: content/facts/public（公開して良い最小限のスナップショット）

## public に入れてよいもの
- store / range / level
- peak_time / avoid_time / crowd_label など「記事に出して良い結論」
- 必要最小限の短い時系列（5〜10点、粗い粒度）
- quality_flags（欠損注意など）

## public に入れないもの
- 生ログ（行データ）/ 個票 / 追跡可能な詳細
- 内部事情につながる情報
- 不要に細かい時系列（repo肥大化の原因）

private/ は将来の作業用（コミット禁止）です。