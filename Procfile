# --timeout: /tasks/multi_collect は全店舗巡回で数十秒〜数分かかる。既定30sだと worker が落ちる
web: gunicorn wsgi:app --timeout 300 --graceful-timeout 30
