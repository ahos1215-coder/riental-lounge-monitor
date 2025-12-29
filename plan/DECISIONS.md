# DECISIONS
Last updated: 2025-12-29 / commit: fb524be

## 2025-12-29: `.env` は UTF-8 no BOM を必須とする
- Decision: `oriental/config.py` が `.env` を読むため、BOM 付きは不可。
- Rationale: BOM があると `\ufeffSUPABASE_URL` のようにキー名が壊れて接続に失敗する。
- Impact: `.env` は no BOM で保存し、手順を docs に明記する。

## 2025-12-29: Supabase Python SDK を必須にしない
- Decision: Supabase SDK は必須にしない。REST (`requests`) を使う。
- Rationale: Windows/Python 3.14 で依存関係が失敗しやすい。
- Impact: `requirements.txt` には SDK を入れない。

## 2025-12-29: Public facts を repo にコミットする
- Decision: `frontend/content/facts/public/*.json` と `index.json` を commit 対象とする。
- Rationale: blog 表示と公開Factsの再現性を担保する。
- Impact: `npm run facts:generate` + `node scripts/build-public-facts-index.mjs` を運用手順に含める。

## 2025-12-29: Blog preview gate を metadata にも適用する
- Decision: draft 記事の metadata は preview token 一致時のみ返す。
- Rationale: draft の title/description 漏れを防ぐ。
- Impact: `BLOG_PREVIEW_TOKEN` を server-only env で管理する。

## 2025-12-17: Supabase `logs` を唯一の Source of Truth にする
- Decision: 観測データの正本は Supabase `logs`。
- Impact: Google Sheet/GAS は legacy fallback のみ（拡張しない）。

## 2025-12-17: レイヤ構造は Supabase → Flask → Next.js に固定
- Decision: フロントから Supabase 直叩きはしない。

## 2025-12-17: 夜窓(19:00-05:00)はフロント責務
- Decision: `/api/range` に時間フィルタを追加しない。

## 2025-12-17: `/api/range` の公開契約は `store` + `limit`
- Decision: `from/to` などは公開契約に含めない。

## 2025-12-17: Second venues は map-link 方針
- Decision: Places API 収集・保存型に戻さない。

## 2025-12-17: Forecast は `ENABLE_FORECAST=1` のみ有効
- Decision: 無効時は `503 { ok:false, error:"forecast-disabled" }` を返す。

## 2025-12-17: 本番収集の入口は `/tasks/multi_collect`
- Decision: `/tasks/tick` は legacy（単店/ローカル/GAS向け）。

## 2025-12-17: Secrets を Git に含めない
- Decision: `.env` / `.env.local` は commit しない。
- Impact: `NEXT_PUBLIC_*` に秘密値禁止。

## 2025-12-17: 低コスト運用前提
- Decision: 追加課金の依存（Places API など）は optional に留める。
