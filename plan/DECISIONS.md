# DECISIONS
Last updated: 2025-12-29 / commit: 4299ff1

## 2025-12-29: `.env` は UTF-8 no BOM を必須とする
- 決定: `oriental/config.py` が `.env` を読むため、BOM 付きは不可。
- 理由: BOM があると `\ufeffSUPABASE_URL` のようにキー名が壊れて接続に失敗する。
- 影響: `.env` は no BOM で保存し、手順を docs に明記する。

## 2025-12-29: Supabase Python SDK を必須にしない
- 決定: Supabase SDK は必須にしない。REST (`requests`) を使う。
- 理由: Windows/Python 3.14 で依存関係が失敗しやすい。
- 影響: `requirements.txt` には SDK を入れない。

## 2025-12-29: Public facts を repo にコミットする
- 決定: `frontend/content/facts/public/*.json` と `index.json` を commit 対象とする。
- 理由: blog 表示と公開Factsの再現性を担保する。
- 影響: `npm run facts:generate` + `node scripts/build-public-facts-index.mjs` を運用手順に含める。

## 2025-12-29: Blog preview gate を metadata にも適用する
- 決定: draft 記事の metadata は preview token 一致時のみ返す。
- 理由: draft の title/description 漏れを防ぐ。
- 影響: `BLOG_PREVIEW_TOKEN` を server-only env で管理する。

## 2025-12-17: Supabase `logs` を唯一の Source of Truth にする
- 決定: 観測データの正本は Supabase `logs`。
- 影響: Google Sheet/GAS は legacy fallback のみ（拡張しない）。

## 2025-12-17: レイヤ構造は Supabase → Flask → Next.js に固定
- 決定: フロントから Supabase 直叩きはしない。

## 2025-12-17: 夜窓(19:00-05:00)はフロント責務
- 決定: `/api/range` に時間フィルタを追加しない。

## 2025-12-17: `/api/range` の公開契約は `store` + `limit`
- 決定: `from/to` などは公開契約に含めない。

## 2025-12-17: Second venues は map-link 方針
- 決定: Places API 収集・保存型に戻さない。

## 2025-12-17: Forecast は `ENABLE_FORECAST=1` のみ有効
- 決定: 無効時は `503 { ok:false, error:"forecast-disabled" }` を返す。

## 2025-12-17: 本番収集の入口は `/tasks/multi_collect`
- 決定: `/tasks/tick` は legacy（単店/ローカル/GAS向け）。

## 2025-12-17: Secrets を Git に含めない
- 決定: `.env` / `.env.local` は commit しない。
- 影響: `NEXT_PUBLIC_*` に秘密値禁止。

## 2025-12-17: 低コスト運用前提
- 決定: 追加課金の依存（Places API など）は optional に留める。
