# 予測レビュー 進捗メモ（Codex が更新するファイル）

> このファイルは **Codex（ChatGPT）が自分のために書く引き継ぎメモ**です。
> 利用上限で中断した後、次回起動時にここを読んで続きから再開します。
> 指示書は `plan/FORECAST_REVIEW_2026-08-22.md`。人間（オーナー）とClaudeも状況確認のためにここを読みます。

STATUS: COMPLETE
UPDATED: 2026-08-22 JST
NEXT: 完了済み。追加作業なし。
DONE: 指示書全文読了。(a)〜(h)をCONFIRMED/OVERSTATED/REFUTED/INCOMPLETEで再判定し、V1〜V11、1日で終わる先頭施策を含む優先ロードマップ、非技術者向け3行を指定形式で `plan/FORECAST_REVIEW_FINDINGS.md` に作成。静的コード、公開GET（100件以内）、LightGBM/SciPy/時系列区間の一次資料で検証。Python import/pytest・禁止スクリプト・秘密ファイル閲覧・外部POST・git操作は行っていない。
FINDINGS: 最終結論は、現行予測は方向感の参考にはなるが公開精度根拠は未監査。(1) Aとbaselineのslot集合が異なり39/42勝利とweight入力は無効、(2) `live_mae`は18:10 pre-openで開店後ユーザー予測ではない、(3) valid nightのfilter順とUIのn表示が不正、(4) served/clamp済み値の自己参照を確認、ただし0.167/0.309は一般解でない、(5) `next_morning_rain`は84/84重要度0で主因説を反証、代わりに全84モデルが使う `total_slope_30min` のone-step/full-night時点不一致を高優先で発見、(6) 最初の1日はproduction weight自動更新を凍結し現行値を保持する。

最終レポートの出力先: `plan/FORECAST_REVIEW_FINDINGS.md`
