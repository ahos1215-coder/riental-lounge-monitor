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
# --max-requests 6000 --max-requests-jitter 200: メモリリークの安全網。ワーカーは
# 累計 6000(±200) リクエストで graceful recycle され、少しずつ肥大するプロセスを
# 定期的に作り直す。--preload なしなのでモデルは各ワーカーが必要時に lazy-load する
# （oriental/routes/forecast.py の _service() → ForecastService → model_registry.get_bundle()。
# create_app() が preload スレッドも再起動する）。6000 件ごとの再生成頻度なら
# モデル再ロードのコストは償却され、リサイクル直後のワーカーもエラーではなく
# 「最初の1リクエストだけ遅い」で degrade する。jitter で全ワーカー同時リサイクルを避ける。
#
# 【2026-08-21 外部レビュー F4: 1500→6000 に引き上げ】gunicorn は WSGI アプリを
# 呼ぶ**前**にこのカウンタを進める（gthread.py の self.nr += 1 は self.wsgi(...) より前）。
# つまり `/api/*` のレート制限（oriental/routes/common.py の InProcessRateLimiter）が
# 429 を返して弾いたリクエストもこのカウンタに乗る。429 は Supabase 往復が無く軽いため、
# 連打されるとこの副作用だけで再生成が速く到達しうる——再生成のたびに
# InProcessRateLimiter の記憶（IP ごとの直近1分カウント）が空になり、42店ぶんのモデル
# preload もやり直しになる（ローカル再現済み: --max-requests 5 で 200×3 + 429×2 の
# 計5件でリサイクルし、新プロセスで再び200が通ることを確認）。
# 1500→6000 は**根絶ではなく緩和**（429 が交ざっても目視で追える程度まで到達を遅らせるだけで、
# 429 を数え間違えている根本自体は残る）。それでも --max-requests 自体は外さない
# （メモリ増加の安全網としての役目は別に必要で、429 副作用のためだけに無効化すると
# 本来のメモリ対策を失う）。数値を大きくしすぎない理由は、無効化に近づくほど
# メモリリーク対策としての効果が薄れるため（Render Starter 512MB の器は変わらない）。
# 【2026-07-17 メモリ成長事件#2】既定を workers 2→1 / threads 4→8 に変更。
# 根拠: Render Starter は 0.5 vCPU のため2プロセス目は「CPU並列にならないのに
# メモリ床だけ2倍(モデル84個×2セット≒+180MB)」の純コスト。LightGBM predict は
# ネイティブ計算中に GIL を解放するのでスレッドでも実用上並行する。
# MALLOC_ARENA_MAX=2 は glibc の malloc arena 増殖(スレッド数に比例して RSS が
# 断片化で膨らむ既知問題)の定番対策。
web: env MALLOC_ARENA_MAX=2 gunicorn wsgi:app --timeout 300 --graceful-timeout 30 --workers ${WEB_CONCURRENCY:-1} --threads ${GUNICORN_THREADS:-8} --max-requests 6000 --max-requests-jitter 200
