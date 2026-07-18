"""Fable監査 Batch B5 bug#7: モデル更新伝播の「15分に1店ずつ」問題の回帰テスト。

背景: model_registry はグローバル単一の _next_refresh_unix しか持たず、
refresh ウィンドウが来た時にリクエストをトリガーした「1店舗だけ」の
モデル名チェック/再構築を行っていた。日次再学習(05:30)後、全42店舗へ
新モデルが伝播しきるまでの期待値は約45時間（15分ウィンドウ×店舗ごとに
偶然トリガーになるのを待つ）で、静かな店舗ほど何日も古いモデルを配信し
続けていた。加えて current_status()/healthz はアルファベット先頭の1店舗
(ay_chiba) の trained_at/schema_version しか見ていなかった。

修正:
  1. refresh ウィンドウ到来時、metadata は既に手元にあるので既知の全店舗に
     対して名前チェック(安価)をループし、実体が変わった店舗だけ再ダウン
     ロード/再パースする。0.5vCPU での CPU スパイクを避けるため、実際の
     再パースは MODEL_REFRESH_BATCH (既定10) 件/ウィンドウに制限する。
  2. ダウンロード/パースはロックを保持せずに行う (lock-free download)。
  3. current_status() は trained_at_min/trained_at_max + ロード済み店舗数を
     追加で返す (既存キーは維持)。

本ファイルは 1. と 2. の回帰テスト。3. (healthz honesty) は tests/test_health.py 側。
"""

from __future__ import annotations

import copy
import threading

from oriental.ml import model_registry as mr


class _FakeModel:
    pass


def _entry(date_str: str, store: str) -> dict:
    return {
        "model_men": f"model_{store}_{date_str}_men.txt",
        "model_women": f"model_{store}_{date_str}_women.txt",
    }


def _make_registry(tmp_path, *, refresh_batch: int = 10, refresh_sec: int = 900):
    return mr.ForecastModelRegistry(
        supabase_url="https://example.supabase.co",
        service_role_key="test-key",
        bucket="ml-models",
        model_prefix="forecast/latest",
        schema_version="v7",
        cache_dir=tmp_path,
        refresh_sec=refresh_sec,
        request_timeout_sec=5.0,
        download_retry=1,
        logger=__import__("logging").getLogger("test"),
        refresh_batch=refresh_batch,
    )


def _wire(reg, monkeypatch, meta: dict, calls: dict, *, download_hook=None):
    def _download(name, path):
        if download_hook:
            download_hook(name)
        calls["download"] = calls.get("download", 0) + 1

    monkeypatch.setattr(reg, "_download_to_cache", _download)
    monkeypatch.setattr(reg, "_load_metadata", lambda path: copy.deepcopy(meta))
    monkeypatch.setattr(reg, "_validate_metadata", lambda m: None)
    monkeypatch.setattr(
        mr.ForecastModel,
        "from_files",
        classmethod(
            lambda cls, *, model_men_path, model_women_path: (
                calls.__setitem__("from_files", calls.get("from_files", 0) + 1) or _FakeModel()
            )
        ),
    )


def _meta(store_ids, date_str, trained_at="2026-07-17T05:30:00+00:00"):
    return {
        "schema_version": "v7",
        "has_store_models": True,
        "trained_at": trained_at,
        "store_models": {sid: _entry(date_str, sid) for sid in store_ids},
    }


def test_sweep_visits_all_known_stores_but_reloads_only_changed(tmp_path, monkeypatch):
    """1店舗だけ名前が変わっても、ループ自体は既知の全店舗を訪れる。再パースは
    変わった店舗だけ。"""
    stores = ["ol_a", "ol_b", "ol_c"]
    meta = _meta(stores, "20260716")
    calls = {}
    reg = _make_registry(tmp_path)
    _wire(reg, monkeypatch, meta, calls)

    for sid in stores:
        reg._next_refresh_unix = 0.0
        reg.get_bundle(store_id=sid)
    assert calls["from_files"] == 3

    # 05:30再学習を模擬: ol_b だけ新しい日付のモデル名になる
    meta["store_models"]["ol_b"] = _entry("20260717", "ol_b")

    visited: list[str] = []
    orig_resolve = reg._resolve_model_names

    def _spy_resolve(metadata, store_id):
        visited.append(store_id)
        return orig_resolve(metadata, store_id)

    monkeypatch.setattr(reg, "_resolve_model_names", _spy_resolve)

    reg._next_refresh_unix = 0.0
    reg.get_bundle(store_id="ol_a")  # ol_a がトリガー（自身は不変）

    assert set(visited) == {"ol_a", "ol_b", "ol_c"}, "名前チェックは既知の全店舗を巡回する"
    assert calls["from_files"] == 4, "実体が変わった ol_b だけ再パースされる (3 + 1)"

    b_bundle = reg.get_bundle(store_id="ol_b")
    assert b_bundle.model_names == (
        "model_ol_b_20260717_men.txt",
        "model_ol_b_20260717_women.txt",
    )


def test_unchanged_metadata_sweep_zero_reparse_across_all_stores(tmp_path, monkeypatch):
    """metadata の中身が完全に不変なら、ウィンドウが経過してもどの店舗も再パースされない。"""
    stores = [f"ol_{i}" for i in range(5)]
    meta = _meta(stores, "20260716")
    calls = {}
    reg = _make_registry(tmp_path)
    _wire(reg, monkeypatch, meta, calls)

    for sid in stores:
        reg._next_refresh_unix = 0.0
        reg.get_bundle(store_id=sid)
    assert calls["from_files"] == 5

    reg._next_refresh_unix = 0.0
    reg.get_bundle(store_id="ol_0")  # ウィンドウ経過だがモデル実体は不変

    assert calls["from_files"] == 5, "metadata不変ならゼロ再パース"
    assert calls["download"] >= 6, "metadata.json自体は毎ウィンドウ取得される"


def test_refresh_batch_cap_honored_and_drains_across_windows(tmp_path, monkeypatch):
    """再学習直後に全店舗の名前が一斉に変わっても、1ウィンドウの再パースは
    refresh_batch 件までに抑えられ、複数ウィンドウにかけて完全伝播する。"""
    n = 5
    stores = [f"ol_{i}" for i in range(n)]
    meta = _meta(stores, "20260716")
    calls = {}
    reg = _make_registry(tmp_path, refresh_batch=2)
    _wire(reg, monkeypatch, meta, calls)

    for sid in stores:
        reg._next_refresh_unix = 0.0
        reg.get_bundle(store_id=sid)
    assert calls["from_files"] == n

    # 一斉再学習: 全店舗のモデル名が新しくなる
    for sid in stores:
        meta["store_models"][sid] = _entry("20260717", sid)

    # ウィンドウ1: cap=2 で頭打ち
    reg._next_refresh_unix = 0.0
    reg.get_bundle(store_id="ol_0")
    assert calls["from_files"] == n + 2, "1ウィンドウの再パースはrefresh_batchで頭打ち"

    # ウィンドウ2: 残りのうち2件が進む
    reg._next_refresh_unix = 0.0
    reg.get_bundle(store_id="ol_0")
    assert calls["from_files"] == n + 4

    # ウィンドウ3: 最後の1件が完了、以降は増えない
    reg._next_refresh_unix = 0.0
    reg.get_bundle(store_id="ol_0")
    assert calls["from_files"] == n + 5, "5店舗すべてが3ウィンドウ以内(cap=2)で伝播完了"

    reg._next_refresh_unix = 0.0
    reg.get_bundle(store_id="ol_0")
    assert calls["from_files"] == n + 5, "伝播完了後は追加の再パースが発生しない"

    for sid in stores:
        bundle = reg.get_bundle(store_id=sid)
        assert bundle.model_names == (
            f"model_{sid}_20260717_men.txt",
            f"model_{sid}_20260717_women.txt",
        ), f"{sid} が新モデルへ伝播していない"


def test_trigger_store_always_processed_even_when_batch_exhausted(tmp_path, monkeypatch):
    """トリガー店舗(=今まさにリクエストされている店舗)は常に先頭で処理され、
    refresh_batch の予算切れの影響を受けない。"""
    stores = ["ol_a", "ol_b", "ol_c"]
    meta = _meta(stores, "20260716")
    calls = {}
    reg = _make_registry(tmp_path, refresh_batch=1)
    _wire(reg, monkeypatch, meta, calls)

    for sid in stores:
        reg._next_refresh_unix = 0.0
        reg.get_bundle(store_id=sid)
    assert calls["from_files"] == 3

    for sid in stores:
        meta["store_models"][sid] = _entry("20260717", sid)

    reg._next_refresh_unix = 0.0
    bundle = reg.get_bundle(store_id="ol_c")  # cap=1 でもトリガー店舗自身は必ず更新される

    assert bundle.model_names == (
        "model_ol_c_20260717_men.txt",
        "model_ol_c_20260717_women.txt",
    )
    assert calls["from_files"] == 4, "トリガー店舗の1件だけがこのウィンドウで再パースされる"


def test_current_status_trained_at_min_max_reflect_stale_propagation(tmp_path, monkeypatch):
    """current_status() は trained_at_min/trained_at_max + ロード済み店舗数を返し、
    capで見送られた店舗が古い metadata のままであることを可視化する。"""
    stores = ["ol_a", "ol_b"]
    meta = _meta(stores, "20260715", trained_at="2026-07-16T05:30:00+00:00")
    calls = {}
    reg = _make_registry(tmp_path, refresh_batch=10)
    _wire(reg, monkeypatch, meta, calls)

    for sid in stores:
        reg._next_refresh_unix = 0.0
        reg.get_bundle(store_id=sid)

    status = reg.current_status()
    assert status["loaded_store_count"] == 2
    assert status["trained_at_min"] == status["trained_at_max"] == "2026-07-16T05:30:00+00:00"
    # 既存キーは維持されている（後方互換）
    assert status["loaded"] is True
    assert status["stores_loaded"] == ["ol_a", "ol_b"]
    assert status["schema_version"] == "v7"

    # 05:30再学習: 新しい trained_at + 両店舗ともモデル名が変わる。cap=1 なので
    # このウィンドウでは1店舗しか伝播しない。
    reg.refresh_batch = 1
    meta["trained_at"] = "2026-07-17T05:30:00+00:00"
    meta["store_models"]["ol_a"] = _entry("20260717", "ol_a")
    meta["store_models"]["ol_b"] = _entry("20260717", "ol_b")

    reg._next_refresh_unix = 0.0
    reg.get_bundle(store_id="ol_a")  # トリガー店舗が予算を使い切る

    status = reg.current_status()
    assert status["loaded_store_count"] == 2
    assert status["trained_at_max"] == "2026-07-17T05:30:00+00:00", "更新できた店舗の新trained_at"
    assert status["trained_at_min"] == "2026-07-16T05:30:00+00:00", (
        "capで見送られたol_bは古いtrained_atのまま=healthzで滞留が見える"
    )


def test_download_does_not_hold_registry_lock(tmp_path, monkeypatch):
    """ダウンロード/パース中は registry lock を保持しない (lock-free download)。

    保持していれば、別スレッドからの _lock.acquire(timeout=...) がタイムアウトする。
    """
    stores = ["ol_a"]
    meta = _meta(stores, "20260716")
    calls = {}
    reg = _make_registry(tmp_path)

    download_started = threading.Event()
    release_download = threading.Event()

    def _hook(name):
        if name == "metadata.json":
            download_started.set()
            # ダウンロード処理中に registry lock を保持していたら、メインスレッドの
            # acquire(timeout=...) がここでブロックされ続けタイムアウトするはず。
            release_download.wait(timeout=2.0)

    _wire(reg, monkeypatch, meta, calls, download_hook=_hook)

    result: dict = {}

    def _run():
        result["bundle"] = reg.get_bundle(store_id="ol_a")

    t = threading.Thread(target=_run)
    t.start()
    try:
        assert download_started.wait(timeout=2.0), "ダウンロードが開始されなかった"

        acquired = reg._lock.acquire(timeout=0.5)
        assert acquired, "download中にregistry lockが保持されたまま(lock-free化されていない)"
        reg._lock.release()
    finally:
        release_download.set()
        t.join(timeout=5.0)

    assert not t.is_alive(), "バックグラウンドスレッドが完了しなかった"
    assert result.get("bundle") is not None
    assert result["bundle"].model_names == (
        "model_ol_a_20260716_men.txt",
        "model_ol_a_20260716_women.txt",
    )


def test_solo_load_of_new_store_does_not_consume_refresh_batch(tmp_path, monkeypatch):
    """まだ refresh ウィンドウが到来していない間に新規店舗が初回リクエストされた場合、
    その単独ロードは refresh_batch の予算を消費しない（sweepとは別経路）。"""
    stores = ["ol_a"]
    meta = _meta(stores, "20260716")
    calls = {}
    reg = _make_registry(tmp_path, refresh_batch=1, refresh_sec=900)
    _wire(reg, monkeypatch, meta, calls)

    reg._next_refresh_unix = 0.0
    reg.get_bundle(store_id="ol_a")  # sweep起動、window claimされる (次回まで900秒先)
    assert calls["from_files"] == 1

    # 新規店舗 ol_new を metadata に追加し、ウィンドウ未到来のまま初回リクエスト
    meta["store_models"]["ol_new"] = _entry("20260716", "ol_new")
    bundle = reg.get_bundle(store_id="ol_new")

    assert bundle is not None
    assert calls["from_files"] == 2, "新規店舗の初回ロードはrefresh_batchの外で必ず成功する"
