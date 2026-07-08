# --timeout: /tasks/multi_collect は全店舗巡回で数十秒〜数分かかる。既定30sだと worker が落ちる
#
# --preload は意図的に付けていない。oriental/__init__.py の create_app() は
# ENABLE_FORECAST=1（本番設定）のとき _preload_models を daemon thread で起動する
# （app 初期化中に thread.start() が呼ばれる = import/preload 完了前からバックグラウンド
# スレッドが動いている）。gunicorn --preload はマスタープロセスで一度だけ app を読み込み、
# その後 fork() でワーカーを複製するが、fork はマスターの「fork を呼んだスレッドだけ」を
# 子プロセスに引き継ぎ、他の実行中スレッド（ここでは preload 用スレッド）は子側に存在しなくなる。
# 結果、preload スレッドがモデルロード中に確保したロック/内部状態を保持したまま消え、
# 子ワーカーがデッドロックしたり不完全なモデルレジストリを参照する恐れがある
# （classic "fork after thread creation" hazard）。安全性を優先し、代わりに並行処理能力は
# ワーカーあたりのスレッド数だけを引き上げる（2 -> 4）。これは同一プロセス内の並行 I/O 待ち
# （コールド店舗で range/forecast_today/range_multi が同時に来るケース）を緩和しつつ、
# fork 前提の共有メモリ最適化には手を出さない安全側の選択。
web: gunicorn wsgi:app --timeout 300 --graceful-timeout 30 --workers ${WEB_CONCURRENCY:-2} --threads ${GUNICORN_THREADS:-4}
