"""スレッドセーフな TTL キャッシュ + single-flight 合流。

`oriental/routes/data.py`（/api/range, /api/range_multi）と
`oriental/routes/forecast.py`（/api/forecast_today 等）の両方が
「アプリプロセス内で結果を短時間キャッシュしつつ、同じキーへの同時
アクセスは1回だけ計算する」という全く同じ性質を必要とするため、
ここに集約する（Flask やこの2ファイル固有の知識を一切持たない、
プレーンな Python オブジェクト）。

なぜ single-flight が要るか:
  店舗ページ1回の表示で、サーバー側レンダリングとクライアント側の
  fetch がほぼ同時に同じ forecast_today / range を叩く。TTL キャッシュ
  だけだと「両方とも cold」なタイミングで2回とも重い処理（ML推論 /
  Supabase 問い合わせ）を実行してしまう。single-flight は片方だけに
  計算させ、もう片方はその結果を待って共有することで、この重複実行を
  防ぐ。

gunicorn はマルチプロセス（複数ワーカー）で動くため、このロックは
あくまで「1プロセス内」でのみ有効。プロセスをまたいだ合流は行わない
し、行う必要もない —— 各ワーカープロセスが自分のキャッシュを持つだけ
で正しさに影響はなく、単に「ワーカー数 × 1回」の重複が起こり得るのみ
（現状の「リクエスト数 × 1回」からの改善としては十分）。
"""

from __future__ import annotations

import threading
from time import monotonic as _clock
from typing import Callable, Generic, TypeVar

T = TypeVar("T")

__all__ = ["SingleFlightTTLCache"]


class _Call(Generic[T]):
    __slots__ = ("event", "data", "error")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.data: T | None = None
        self.error: BaseException | None = None


class SingleFlightTTLCache(Generic[T]):
    """TTL 付きキャッシュ。同一キーへの同時アクセスは1回だけ計算する。

    Parameters
    ----------
    ttl:
        エントリの有効秒数。
    max_entries:
        `_store` のサイズ上限。超えたら（シンプルさ優先で）全消去してから
        新しいエントリを入れる。個別 LRU は実装しない —— どうせ TTL で
        すぐ再構築されるため、複雑さに見合わない。
    wait_timeout:
        他スレッドの計算待ち（合流）を諦めるまでの秒数。計算側スレッドが
        異常に長くかかった/ハングした場合でも、待っている側がここで
        タイムアウトして自分で計算し直す（fail-open）ため、デッドロック
        やリクエストの無限ハングを避けられる。
    """

    def __init__(self, ttl: float, *, max_entries: int = 500, wait_timeout: float = 25.0) -> None:
        self._ttl = ttl
        self._max_entries = max_entries
        self._wait_timeout = wait_timeout
        self._lock = threading.Lock()
        self._store: dict[str, tuple[float, T]] = {}
        self._inflight: dict[str, _Call[T]] = {}

    # ---- 単純な get/set（single-flight を使わない直接アクセス用） ----

    def _get_locked(self, key: str) -> T | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        at, data = entry
        if _clock() - at > self._ttl:
            self._store.pop(key, None)
            return None
        return data

    def get(self, key: str) -> T | None:
        with self._lock:
            return self._get_locked(key)

    def set(self, key: str, data: T) -> None:
        with self._lock:
            if len(self._store) > self._max_entries:
                # 個別 eviction はせず全消去する（すぐ再構築されるため十分）。
                self._store.clear()
            self._store[key] = (_clock(), data)

    def invalidate(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def size(self) -> int:
        with self._lock:
            return len(self._store)

    # ---- single-flight 合流付きの計算 ----

    def get_or_compute(
        self, key: str, compute_fn: Callable[[], tuple[T, bool]]
    ) -> tuple[T, str]:
        """`key` の値を返す。cold なら compute_fn() で計算する。

        compute_fn() は `(data, cacheable)` を返すこと。`cacheable=False`
        の結果（例: 上流エラー）は TTL ストアに書き込まれない —— 次の
        リクエストがすぐ再試行できるようにするため。

        戻り値は `(data, status)`。status は以下のいずれか:
          "hit"       - 有効なキャッシュから計算なしで返した。
          "miss"      - このスレッドが実際に計算した（cold だった）。
          "coalesced" - 他スレッドの計算中に合流し、その結果を共有した。
          "timeout"   - 合流待ちが wait_timeout を超えたため、
                        fail-open で自分でも計算した。
        """
        with self._lock:
            cached = self._get_locked(key)
            if cached is not None:
                return cached, "hit"

            call = self._inflight.get(key)
            if call is not None:
                is_leader = False
            else:
                call = _Call()
                self._inflight[key] = call
                is_leader = True

        if is_leader:
            try:
                data, cacheable = compute_fn()
            except BaseException as exc:  # noqa: BLE001 - 待機側にも伝播させる
                call.error = exc
                raise
            finally:
                with self._lock:
                    self._inflight.pop(key, None)
                call.event.set()
            call.data = data
            if cacheable:
                self.set(key, data)
            return data, "miss"

        finished = call.event.wait(self._wait_timeout)
        if finished:
            if call.error is not None:
                raise call.error
            return call.data, "coalesced"  # type: ignore[return-value]

        # fail-open: 合流待ちがタイムアウト -> 自分で計算する（デッドロック防止）
        data, cacheable = compute_fn()
        if cacheable:
            self.set(key, data)
        return data, "timeout"
