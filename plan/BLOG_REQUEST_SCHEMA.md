# BLOG_REQUEST_SCHEMA
Last updated: 2025-12-29 / commit: 4299ff1

LINE 依頼 → n8n 受付 → Facts/MDX 生成の「最小入力」を固定するための SSOT。
実装は次フェーズで行い、ここでは契約（スキーマと境界）だけを定義する。

## 目的
- LINE 依頼の最小入力を「壊れにくい形」で固定する。
- request から facts_id / slug / date / store を機械的に決定できるようにする。
- 出力（facts/MDX/PR）の粒度と置き場所を固定し、手戻りを小さくする。

## Request (minimum)
```json
{
  "request_id": "uuid-or-yyyymmddhhmmss",
  "store_id": "shibuya",
  "target_date": "2025-12-21",
  "kind": "tonight",
  "angle": "first-visit",
  "tone": "calm",
  "notes": "禁止表現や入れたい一文など"
}
```

## JSON Schema (v0)
```json
{
  "type": "object",
  "required": ["request_id", "store_id", "target_date", "kind"],
  "properties": {
    "request_id": {
      "type": "string",
      "description": "uuid か yyyymmddhhmmss などの一意 ID"
    },
    "store_id": {
      "type": "string",
      "description": "store slug (例: shibuya)"
    },
    "target_date": {
      "type": "string",
      "format": "date",
      "description": "YYYY-MM-DD (JST)"
    },
    "kind": {
      "type": "string",
      "enum": ["tonight", "weekly", "howto"],
      "description": "用途種別。追加は将来拡張で可"
    },
    "angle": {
      "type": "string",
      "enum": ["first-visit", "comparison", "timing", "safety"],
      "description": "任意。記事の切り口"
    },
    "tone": {
      "type": "string",
      "enum": ["calm", "friendly", "serious"],
      "description": "任意。文章トーン"
    },
    "notes": {
      "type": "string",
      "description": "任意。禁止表現や入れたい一文など"
    }
  },
  "additionalProperties": true
}
```

## request → facts_id / slug / date / store の決定ルール
- `store_id` は store slug として扱う（例: `shibuya`）。
- `target_date` は JST の日付（`YYYY-MM-DD`）として扱う。
- `facts_id_public` / `slug` は以下で決定する（plan/BLOG_PIPELINE.md の命名と整合）:
  - `facts_id_public = {store_id}-{kind}-{yyyymmdd}`
  - `slug = facts_id_public`
  - 例: `shibuya-tonight-20251221`
- `yyyymmdd` は `target_date` を `YYYYMMDD` に変換したもの。
- `kind` が `weekly` / `howto` の場合も、ID は同ルールで一意性を確保する。

## 生成物（最小セット）
- Facts 完全版（Supabase: facts_full）※ repo には保存しない
- 公開 Facts（JSON）: `frontend/content/facts/public/<facts_id_public>.json`
- MDX ドラフト: `frontend/content/blog/<slug>.mdx`（`draft: true`）
- PR: 上記成果物を含む Pull Request

## 変えてよい / 変えない境界
変えてよい（後方互換を守る）
- `kind` / `angle` / `tone` の列挙値追加
- 追加フィールド（必須化しない）
- `notes` の運用ルール（禁止表現の辞書など）

変えない（契約固定）
- 必須キー名: `request_id`, `store_id`, `target_date`, `kind`
- `store_id` は store slug として扱う
- `target_date` は `YYYY-MM-DD`（JST）
- `facts_id_public` / `slug` の命名規則（`{store_id}-{kind}-{yyyymmdd}`）
- 公開 Facts / MDX の保存場所
