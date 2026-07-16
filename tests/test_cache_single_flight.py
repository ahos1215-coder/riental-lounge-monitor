"""oriental/routes/_cache.py の SingleFlightTTLCache のテスト。

/api/range 系（oriental/routes/data.py）と /api/forecast_today 系
（oriental/routes/forecast.py）が共通で使う「TTL キャッシュ + 同時アクセスの
single-flight 合流」の核となる部品。Flask に依存しないプレーンな Python
オブジェクトなので、ここでは Flask アプリを一切立てずに直接テストする。

カバーする観点（perf: backend cache/coalesce タスクの要求どおり）:
  - TTL キャッシュの hit / expiry
  - キーの正規化（別キーは衝突しない・同じキーはヒットする）
  - single-flight 合流（同時アクセスは1回だけ計算される）
  - 合流待ちタイムアウトの fail-open（自分で計算し直す）
  - スレッドセーフのスモークテスト
"""

from __future__ import annotations

import threading
import time as time_module

import pytest

from oriental.routes._cache import SingleFlightTTLCache


def test_hit_returns_cached_value_without_recompute():
    cache = SingleFlightTTLCache(ttl=60)
    calls: list[int] = []

    def compute():
        calls.append(1)
        return "value", True

    data1, status1 = cache.get_or_compute("k", compute)
    data2, status2 = cache.get_or_compute("k", compute)

    assert (data1, status1) == ("value", "miss")
    assert (data2, status2) == ("value", "hit")
    assert len(calls) == 1


def test_expiry_triggers_recompute(monkeypatch):
    fake_time = [0.0]
    monkeypatch.setattr("oriental.routes._cache._clock", lambda: fake_time[0])

    cache = SingleFlightTTLCache(ttl=10)
    calls: list[int] = []

    def compute():
        calls.append(1)
        return "value", True

    cache.get_or_compute("k", compute)
    assert len(calls) == 1

    fake_time[0] = 5.0  # TTL 内 -> まだ有効
    _, status = cache.get_or_compute("k", compute)
    assert status == "hit"
    assert len(calls) == 1

    fake_time[0] = 10.1  # TTL 超過 -> 再計算
    _, status = cache.get_or_compute("k", compute)
    assert status == "miss"
    assert len(calls) == 2


def test_key_normalization_distinguishes_and_reuses_entries():
    cache = SingleFlightTTLCache(ttl=60)
    calls: dict[str, int] = {}

    def make_compute(key: str):
        def _compute():
            calls[key] = calls.get(key, 0) + 1
            return key, True
        return _compute

    key_a = "ol_gangnam|2026-07-01|2026-07-02|500"
    key_b = "ol_shibuya|2026-07-01|2026-07-02|500"  # store が違う
    key_c = "ol_gangnam|2026-07-01|2026-07-03|500"  # 期間が違う
    key_d = "ol_gangnam|2026-07-01|2026-07-02|100"  # limit が違う

    for key in (key_a, key_b, key_c, key_d):
        data, status = cache.get_or_compute(key, make_compute(key))
        assert data == key
        assert status == "miss"

    # 同じキーへの再アクセスはヒットし、再計算されない
    data, status = cache.get_or_compute(key_a, make_compute(key_a))
    assert data == key_a
    assert status == "hit"
    assert calls[key_a] == 1
    assert set(calls) == {key_a, key_b, key_c, key_d}


def test_non_cacheable_result_is_not_persisted():
    """cacheable=False（上流エラーなど）は TTL に乗らない -> 毎回再計算される。"""
    cache = SingleFlightTTLCache(ttl=60)
    calls: list[int] = []

    def compute():
        calls.append(1)
        return "error-body", False

    data1, status1 = cache.get_or_compute("k", compute)
    data2, status2 = cache.get_or_compute("k", compute)

    assert status1 == "miss"
    assert status2 == "miss"
    assert len(calls) == 2
    assert cache.size() == 0


def test_overflow_drops_oldest_quarter_not_whole_store():
    """max_entries 超過時、旧実装のような全消去ではなく最古 ~25% だけを落とす
    （memory-budget 修正。junk キーの洪水で warm エントリを毎回巻き添えにしない）。"""
    cache = SingleFlightTTLCache(ttl=60, max_entries=8)
    for i in range(9):  # 9個目の set で 9 > 8 → evict
        cache.set(f"k{i}", i)

    # 旧実装（全消去）なら size==1。新実装は expired 無し → drop_n = 9//4 = 2 を落として size 7。
    assert cache.size() == 7
    # 最古の k0,k1 が落ち、最新の k8 は残る。
    assert cache.get("k0") is None
    assert cache.get("k1") is None
    assert cache.get("k8") == 8


def test_overflow_drops_expired_before_oldest(monkeypatch):
    """overflow 時はまず TTL 切れ（使い捨て junk）を落とす。fresh な warm は
    たとえ挿入順が古くても巻き添えにしない。"""
    fake_time = [0.0]
    monkeypatch.setattr("oriental.routes._cache._clock", lambda: fake_time[0])

    cache = SingleFlightTTLCache(ttl=10, max_entries=6)
    for i in range(5):  # t=0 に使い捨て junk を5本
        cache.set(f"junk{i}", i)

    fake_time[0] = 20.0  # junk は TTL(10) 超過。warm を入れて overflow を起こす。
    cache.set("warm0", "a")  # size 6（まだ overflow せず）
    cache.set("warm1", "b")  # size 7 > 6 → evict: 期限切れ junk5本を先に落とす

    assert cache.get("warm0") == "a"
    assert cache.get("warm1") == "b"
    for i in range(5):
        assert cache.get(f"junk{i}") is None
    assert cache.size() == 2


def test_warm_keys_survive_junk_flood_via_lru():
    """繰り返しヒットする warm キーは、junk キーの洪水が何度 overflow を
    起こしても LRU touch により生き残る（junk は一度きりで先頭へ流れ落ちる）。"""
    cache = SingleFlightTTLCache(ttl=600, max_entries=10)
    warm = [f"warm{i}" for i in range(5)]
    for k in warm:
        cache.get_or_compute(k, lambda k=k: (k, True))

    for j in range(200):
        # junk を1本流し込むたびに warm 全部を再ヒット（touch で末尾＝最新へ移動）。
        cache.get_or_compute(f"junk{j}", lambda j=j: (j, True))
        for k in warm:
            data, status = cache.get_or_compute(k, lambda k=k: (k, True))
            assert status == "hit"  # warm は evict されず常にキャッシュヒット

    assert cache.size() <= 10
    for k in warm:
        assert cache.get(k) == k


def test_single_flight_coalesces_concurrent_callers():
    cache = SingleFlightTTLCache(ttl=60, wait_timeout=5)
    call_count = [0]
    release = threading.Event()

    def slow_compute():
        call_count[0] += 1
        release.wait(timeout=5)
        return "computed", True

    results: list[tuple] = []
    results_lock = threading.Lock()

    def worker():
        data, status = cache.get_or_compute("k", slow_compute)
        with results_lock:
            results.append((data, status))

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()

    # leader が in-flight に入るのを待ってからフォロワーを解放する
    deadline = time_module.time() + 5
    while call_count[0] < 1 and time_module.time() < deadline:
        time_module.sleep(0.005)
    time_module.sleep(0.1)  # フォロワー4本が合流待ちに入る猶予
    release.set()

    for t in threads:
        t.join(timeout=5)

    assert call_count[0] == 1  # 5並列でも実際の計算は1回だけ
    assert all(data == "computed" for data, _ in results)
    statuses = [s for _, s in results]
    assert statuses.count("miss") == 1
    assert statuses.count("coalesced") == 4


def test_timeout_fallback_computes_independently_and_fails_open():
    cache = SingleFlightTTLCache(ttl=60, wait_timeout=0.2)
    leader_calls = [0]
    leader_release = threading.Event()

    def leader_compute():
        leader_calls[0] += 1
        leader_release.wait(timeout=5)  # フォロワーの wait_timeout(0.2s) より長く待たせる
        return "leader-value", True

    leader_results: list[tuple] = []

    def leader_worker():
        leader_results.append(cache.get_or_compute("k", leader_compute))

    t = threading.Thread(target=leader_worker)
    t.start()

    # leader が in-flight 登録されるのを待つ
    deadline = time_module.time() + 5
    while leader_calls[0] < 1 and time_module.time() < deadline:
        time_module.sleep(0.005)

    # フォロワー: leader がまだブロック中なので wait_timeout(0.2s) で諦め、
    # fail-open で自分自身の compute_fn を実行するはず
    fallback_calls = [0]

    def fallback_compute():
        fallback_calls[0] += 1
        return "fallback-value", True

    data, status = cache.get_or_compute("k", fallback_compute)
    assert status == "timeout"
    assert data == "fallback-value"
    assert fallback_calls[0] == 1

    leader_release.set()
    t.join(timeout=5)
    assert leader_calls[0] == 1
    assert leader_results[0] == ("leader-value", "miss")


def test_exception_in_compute_propagates_and_clears_inflight_state():
    cache = SingleFlightTTLCache(ttl=60)

    def boom():
        raise ValueError("boom")

    with pytest.raises(ValueError):
        cache.get_or_compute("k", boom)

    # in-flight エントリが確実に片付いていること（次の呼び出しが永久に待たされない）
    data, status = cache.get_or_compute("k", lambda: ("ok", True))
    assert (data, status) == ("ok", "miss")


def test_waiting_follower_reraises_leader_exception():
    """leader が例外を投げた場合、合流していたフォロワーにも同じ例外が伝播すること。"""
    cache = SingleFlightTTLCache(ttl=60, wait_timeout=5)
    release = threading.Event()

    def leader_compute():
        release.wait(timeout=5)
        raise RuntimeError("leader-boom")

    errors: list[BaseException] = []
    errors_lock = threading.Lock()

    def leader_worker():
        try:
            cache.get_or_compute("k", leader_compute)
        except BaseException as exc:  # noqa: BLE001
            with errors_lock:
                errors.append(exc)

    t = threading.Thread(target=leader_worker)
    t.start()
    time_module.sleep(0.1)  # leader が in-flight 登録されるのを待つ

    def follower_compute():  # pragma: no cover - フォロワーは合流するので呼ばれない想定
        return "should-not-be-called", True

    with pytest.raises(RuntimeError):
        cache.get_or_compute("k", follower_compute)

    release.set()
    t.join(timeout=5)
    assert len(errors) == 1
    assert isinstance(errors[0], RuntimeError)


def test_thread_safety_smoke_many_keys_many_threads():
    cache = SingleFlightTTLCache(ttl=60)
    errors: list[BaseException] = []
    errors_lock = threading.Lock()

    def worker():
        try:
            for j in range(50):
                key = f"key-{j % 10}"
                cache.get_or_compute(key, lambda key=key: (key, True))
        except BaseException as exc:  # noqa: BLE001 - スモークテストなので何でも拾う
            with errors_lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors
    assert cache.size() <= 10
