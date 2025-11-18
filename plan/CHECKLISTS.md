# CHECKLISTS.md — 運用・リリース・障害対応チェックリスト

## 1. デイリー
- [ ] Render > Events に失敗デプロイが無い
- [ ] `/tasks/tick` の cron が動いている（cron-job.org の Next executions を確認）
- [ ] フロント画面に当日グラフ/数値が出ている

## 2. リリース前
- [ ] `pytest -q` がグリーン
- [ ] `plan/API_CONTRACT.md` の差分確認（互換性）
- [ ] Render の `Environment` 変更点を控える（ENV.md 更新）

## 3. リリース後
- [ ] スモーク: `/api/range?limit=0` が 200 で rows 返却
- [ ] ダッシュボードに反映
- [ ] Render Logs に例外が出ていない

## 4. 障害対応
- [ ] Render Status / Logs を確認
- [ ] `cron-job.org` で 4xx/5xx が続いていないか
- [ ] 直近デプロイなら `Rollback` 実施
- [ ] `TARGET_URL` 側の仕様変更がないか簡易調査
- [ ] 暫定: `/api/*` をスタブ値に切替（既定のスタブは常に 200）

## 5. 月次
- [ ] `plan/CODEx_PROMPTS.md` を 1 回実行し、コードの堅牢化/整形をかける
- [ ] `plan/RUNBOOK.md` の見直し
