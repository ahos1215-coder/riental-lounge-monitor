"""再試行ポリシーの共有ヘルパー（stdlib のみ・サードパーティ import ゼロ）。

2026-08-18 の Supabase 飽和事故のあと、各バッチジョブに個別に指数バックオフを
入れた結果、同じ方針が scripts/backup_logs.py / cleanup_old_logs.py /
cleanup_old_models.py に3本コピーされ、しかも `backoff_delay` の引数順が
バラバラ（backup は第2位置引数が retry_after、models は cap）という
危険な状態になっていた。ここに1本化する。

**待ち秒数は一切変えない**。各スクリプトは自分の cap / 試行回数の定数を持ったまま、
計算式だけをここから import する。統一シグネチャは `backoff_delay(attempt, cap,
retry_after=None)` で、cap は必須（旧 backup_logs / cleanup_old_logs にあった
「モジュール定数を既定値にする」書き方は、どのスクリプトの cap なのかが
呼び出し側から見えなくなるので採らない）。

トップレベルスクリプトとして `python scripts/x.py` 実行される前提なので、
scripts/_supabase_common.py / _night_slots.py と同じ規約で、呼び出し側が
`sys.path.insert(0, <自分のディレクトリ>)` した上でベアインポートする。
"""

from __future__ import annotations


def backoff_delay(attempt: int, cap: float, retry_after: float | None = None) -> float:
    """1始まりの再試行 ``attempt`` に対する指数バックオフ秒数（``cap`` 秒で頭打ち）。

    サーバが ``Retry-After``（秒）を返していて、それが計算値より大きければそちらを
    優先する（Supabase は 429 ``too_many_connections`` に付けてきて、プーラーが実際に
    空くと見込む時刻を反映しているため）。ただし ``cap`` は超えない。

    純粋関数（I/O なし・sleep なし）なので再試行方針を単体テストできる。
    """
    delay = min(float(2 ** attempt), float(cap))
    if retry_after is not None and retry_after > delay:
        delay = min(float(retry_after), float(cap))
    return delay


def is_retryable_status(code: int) -> bool:
    """再試行する価値のある Supabase の飽和シグナルなら True。

    429 = too_many_connections / SlowDown、5xx = 500・544 DatabaseTimeout・502/503/504。
    それ以外の 4xx は本当に不正なリクエスト（認証・不正フィルタ）なので、再試行しても
    バジェットを浪費するだけ。
    """
    return code == 429 or code >= 500
