"""番犬: /api/forecast_snapshot・/api/forecast_accuracy の Storage 取得回数を固定する。

2026-09-05〜09、Supabase 無料枠の egress を使い切って全リクエストが HTTP 402 になり、
サイトが3日半「男性0/女性0」を表示し続けた。この答え合わせ系は転送量の3番目に大きい
消費者だった:
  - /api/forecast_snapshot は accuracy/snapshots/<date>.json（全42店ぶん）を毎回
    まるごと落として1店ぶんだけ返す。scripts/warm_cdn_local.py が毎晩42店ぶん叩くので
    同じファイルを42回落としていた（推定 13〜17 MiB/日）。
  - /api/forecast_accuracy は Cache-Control を付けていない＝CDN で止まらないため、
    summary.json + scores/<date>.json を呼ばれるたびに落としていた。

修正: `_storage_get` を routes/_cache.py の SingleFlightTTLCache（forecast.py /
data_range.py と同じ道具）に載せた。TTL が2種類要るのでインスタンスは2つ
（終わった夜＝長TTL / それ以外＝短TTL）。ここで固定するのは:
  1. 同じオブジェクトの2回目の取得で Storage を叩かない（＝urlopen が増えない）
  2. 別オブジェクト（別 date）は別々に取りに行く
  3. TTL が切れたら取り直す
  4. 例外（402/5xx）はキャッシュしない＝復旧したら次のリクエストで即座に反映される
  5. date は利用者が自由に指定できるので、キャッシュ件数に上限がある
  6. 同じオブジェクトへの同時ミスは single-flight で1回に合流する
     （手書き TTL キャッシュには無く、threads=8 なら最大8本の取得が並走していた）
  7. ok:false の応答を CDN に長く焼き付けないこと（障害中の1回で「記録なし」が
     24時間固定されると、4. の「復旧したら即反映」が1段上で無効化される）は
     tests/test_forecast_snapshot_api.py が固定する。
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error

import pytest

from oriental import create_app
from oriental.routes import forecast_accuracy as fc


def _expire_all(cache) -> None:
    """TTL 切れを模擬する（保存時刻を TTL より前へずらす）。

    SingleFlightTTLCache は「保存時の monotonic 時刻」を持つので、そこを過去へ
    動かすのが time を止めずに期限切れを作る一番素直な方法。
    """
    with cache._lock:
        for key, (stored_at, data) in list(cache._store.items()):
            cache._store[key] = (stored_at - cache._ttl - 1.0, data)


def _total_cached(app) -> int:
    """短TTL・長TTL 両インスタンスの合計エントリ数。"""
    total = 0
    for key in (fc._CACHE_CONFIG_KEY, fc._PAST_CACHE_CONFIG_KEY):
        cache = app.config.get(key)
        if cache is not None:
            total += cache.size()
    return total


class _FakeResp:
    def __init__(self, body: bytes):
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _install_env(monkeypatch, tmp_path):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "key")
    monkeypatch.setenv("FORECAST_MODEL_BUCKET", "ml-models")
    monkeypatch.setenv("DATA_BACKEND", "supabase")


@pytest.fixture
def app(monkeypatch, tmp_path):
    _install_env(monkeypatch, tmp_path)
    return create_app()


def _mock_storage(monkeypatch, bodies: dict[str, dict], urls: list[str]):
    """path の部分一致で JSON を返すフェイク。呼ばれた URL を全部記録する。"""

    def _fake_urlopen(req, timeout=10):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        urls.append(url)
        for needle, payload in bodies.items():
            if needle in url:
                return _FakeResp(json.dumps(payload).encode())
        raise urllib.error.HTTPError(url, 404, "not found", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)


_SNAPSHOT = {
    "night_date": "20260101",
    "by_slug": {
        "nagasaki": [{"ts": "2026-01-01T19:00:00+09:00", "total_pred": 10}],
        "ay_shibuya": [{"ts": "2026-01-01T19:00:00+09:00", "total_pred": 20}],
    },
}


def test_snapshot_second_store_does_not_hit_storage(app, monkeypatch):
    """同じ夜のスナップショットは何店ぶん引いても Storage 取得は1回だけ。

    warm_cdn_local.py の「42店ぶん連続で叩く」動きがそのまま42回のダウンロードに
    なっていたのが、この修正の主目的。
    """
    urls: list[str] = []
    _mock_storage(monkeypatch, {"accuracy/snapshots/20260101.json": _SNAPSHOT}, urls)
    client = app.test_client()

    first = client.get("/api/forecast_snapshot?store=nagasaki&date=20260101")
    second = client.get("/api/forecast_snapshot?store=ay_shibuya&date=20260101")

    assert first.get_json()["ok"] is True
    assert second.get_json()["ok"] is True
    assert second.get_json()["data"] == _SNAPSHOT["by_slug"]["ay_shibuya"]
    assert len(urls) == 1, f"2回目は Storage を叩かない (実際に叩いた URL: {urls})"


def test_snapshot_different_date_is_fetched_separately(app, monkeypatch):
    """キャッシュはオブジェクト単位。別の夜は当然もう1回取りに行く。"""
    urls: list[str] = []
    other = {"night_date": "20260102", "by_slug": {"nagasaki": [{"ts": "x"}]}}
    _mock_storage(
        monkeypatch,
        {
            "accuracy/snapshots/20260101.json": _SNAPSHOT,
            "accuracy/snapshots/20260102.json": other,
        },
        urls,
    )
    client = app.test_client()

    client.get("/api/forecast_snapshot?store=nagasaki&date=20260101")
    client.get("/api/forecast_snapshot?store=nagasaki&date=20260102")
    client.get("/api/forecast_snapshot?store=nagasaki&date=20260101")

    assert len(urls) == 2, "別 date は別々に取得し、同じ date は使い回す"


def test_snapshot_refetched_after_ttl_expires(app, monkeypatch):
    """TTL が切れたら取り直す（永久キャッシュではない）。"""
    urls: list[str] = []
    _mock_storage(monkeypatch, {"accuracy/snapshots/20260101.json": _SNAPSHOT}, urls)
    client = app.test_client()

    client.get("/api/forecast_snapshot?store=nagasaki&date=20260101")
    assert len(urls) == 1

    # 期限切れを模擬（終わった夜の実在ファイルなので長TTL側に入っている）。
    _expire_all(app.config[fc._PAST_CACHE_CONFIG_KEY])

    client.get("/api/forecast_snapshot?store=nagasaki&date=20260101")
    assert len(urls) == 2


def test_storage_error_is_not_cached(app, monkeypatch):
    """402/5xx はキャッシュしない。復旧したら次のリクエストで即座に本物を返す。

    2026-09 の事故そのものの形（Supabase が全リクエストに 402 を返す）で、
    エラーを長時間キャッシュすると復旧後もサイトが空のままになる。
    """
    urls: list[str] = []
    state = {"down": True}

    def _fake_urlopen(req, timeout=10):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        urls.append(url)
        if state["down"]:
            raise urllib.error.HTTPError(url, 402, "Payment Required", {}, None)
        return _FakeResp(json.dumps(_SNAPSHOT).encode())

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    client = app.test_client()

    down = client.get("/api/forecast_snapshot?store=nagasaki&date=20260101")
    assert down.status_code == 200 and down.get_json()["ok"] is False

    state["down"] = False
    recovered = client.get("/api/forecast_snapshot?store=nagasaki&date=20260101")
    assert recovered.get_json()["ok"] is True, "エラーをキャッシュすると復旧が反映されない"
    assert len(urls) == 2


def test_missing_object_is_cached_but_short_lived(app, monkeypatch):
    """404（＝まだ書かれていない夜）は短い TTL でキャッシュする。

    連打で毎回 Storage を叩かせない一方、あとから書かれる（昨夜のスコアは翌 06:10 に
    初めて書かれる）ので長く持たない。
    """
    urls: list[str] = []
    _mock_storage(monkeypatch, {}, urls)  # 何を要求しても 404
    client = app.test_client()

    client.get("/api/forecast_snapshot?store=nagasaki&date=20260101")
    client.get("/api/forecast_snapshot?store=nagasaki&date=20260101")
    assert len(urls) == 1

    short = app.config[fc._CACHE_CONFIG_KEY]
    assert short.get("accuracy/snapshots/20260101.json") == (None,), (
        "未作成（404）は短TTL側に「無い」として記憶する"
    )
    assert short._ttl <= 300.0, "未作成オブジェクトは短命 TTL"
    assert app.config.get(fc._PAST_CACHE_CONFIG_KEY) is None or (
        app.config[fc._PAST_CACHE_CONFIG_KEY].get("accuracy/snapshots/20260101.json") is None
    ), "未作成を長TTL側に載せると、あとから書かれても長時間拾えなくなる"


def test_finished_night_gets_longer_ttl_than_unwritten_one(app, monkeypatch):
    """終わった夜のスナップショット（もう書き換わらない）は長めの TTL を貰う。"""
    urls: list[str] = []
    _mock_storage(monkeypatch, {"accuracy/snapshots/20260101.json": _SNAPSHOT}, urls)
    client = app.test_client()

    client.get("/api/forecast_snapshot?store=nagasaki&date=20260101")  # 過去日・存在する
    client.get("/api/forecast_snapshot?store=nagasaki&date=20260102")  # 過去日・404

    past = app.config[fc._PAST_CACHE_CONFIG_KEY]
    short = app.config[fc._CACHE_CONFIG_KEY]
    assert past.get("accuracy/snapshots/20260101.json") is not None, "実在ファイルは長TTL側"
    assert short.get("accuracy/snapshots/20260102.json") == (None,), "未作成は短TTL側"
    assert past._ttl > short._ttl, "終わった夜の実在ファイルは長め、未作成は短め"
    assert past._ttl > 300.0


def test_ttl_zero_disables_cache(app, monkeypatch):
    """キルスイッチ: TTL=0 なら修正前と同じく毎回取りに行く。"""
    monkeypatch.setenv("FORECAST_ACCURACY_CACHE_TTL", "0")
    monkeypatch.setenv("FORECAST_ACCURACY_PAST_CACHE_TTL", "0")
    urls: list[str] = []
    _mock_storage(monkeypatch, {"accuracy/snapshots/20260101.json": _SNAPSHOT}, urls)
    client = app.test_client()

    client.get("/api/forecast_snapshot?store=nagasaki&date=20260101")
    client.get("/api/forecast_snapshot?store=nagasaki&date=20260101")

    assert len(urls) == 2


def test_cache_entries_are_bounded(app, monkeypatch):
    """date は利用者が自由に指定できるので、キャッシュ件数に上限があること。

    上限が無いと、クローラが日付を変えて叩くだけでプロセスのメモリを食い潰せる
    （0.5vCPU / 少メモリの Render Starter で 84 本のモデルと同居している）。
    """
    urls: list[str] = []
    _mock_storage(monkeypatch, {}, urls)
    client = app.test_client()

    for day in range(1, fc._CACHE_MAX_ENTRIES + 12):
        client.get(f"/api/forecast_snapshot?store=nagasaki&date=202601{day:02d}")

    # 上限は「短TTL＋長TTL の合計」で見る（1本 ~350KB が載るので合計が効く数字）。
    assert _total_cached(app) <= fc._CACHE_MAX_ENTRIES
    assert fc._SHORT_CACHE_MAX_ENTRIES + fc._PAST_CACHE_MAX_ENTRIES == fc._CACHE_MAX_ENTRIES


def test_concurrent_misses_share_one_fetch(app, monkeypatch):
    """同じオブジェクトへの同時ミスは single-flight で1回に合流する。

    手書き TTL キャッシュにはこれが無く、cold な瞬間に同時到達したスレッドの数だけ
    （gunicorn --threads 8 なら最大8本）同じ 350KB を並走ダウンロードしていた。
    warm_cdn_local.py が42店ぶんを一斉に叩く運用なので、まさにこの形で
    「減らしたはずの転送」が漏れる。
    """
    path = "accuracy/snapshots/20260101.json"
    urls: list[str] = []
    urls_lock = threading.Lock()
    release = threading.Event()

    def _fake_urlopen(req, timeout=10):
        with urls_lock:
            urls.append(req.full_url)
        release.wait(10)  # leader を計算中のまま留め、後続を合流させる
        return _FakeResp(json.dumps(_SNAPSHOT).encode())

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    cfg = app.config["APP_CONFIG"]
    results: list[bytes | None] = []
    results_lock = threading.Lock()

    def _call():
        with app.app_context():
            value = fc._storage_get(cfg, path)
        with results_lock:
            results.append(value)

    leader = threading.Thread(target=_call)
    leader.start()

    # leader が「取得中」として登録されるまで待つ（ここまで来れば後続は必ず合流側）。
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        cache = app.config.get(fc._PAST_CACHE_CONFIG_KEY)
        if cache is not None and path in cache._inflight:
            break
        time.sleep(0.005)
    else:  # pragma: no cover - 実行環境が極端に遅いときだけ
        release.set()
        leader.join(10)
        pytest.fail("leader が single-flight に登録されなかった")

    gate = threading.Barrier(8)  # 後続7スレッド + メイン

    def _follower():
        gate.wait(10)
        _call()

    followers = [threading.Thread(target=_follower) for _ in range(7)]
    for t in followers:
        t.start()
    gate.wait(10)
    release.set()

    leader.join(10)
    for t in followers:
        t.join(10)

    assert len(urls) == 1, f"同時ミスは1回に合流する (実際に叩いた URL: {urls})"
    assert len(results) == 8
    assert all(r is not None for r in results), "合流した側も同じ結果を受け取る"


def test_forecast_accuracy_reuses_summary_and_daily(app, monkeypatch, tmp_path):
    """/api/forecast_accuracy の2回目は summary.json も scores/<date>.json も叩かない。"""
    meta = {
        "trained_at": "2026-09-01T00:00:00Z",
        "metrics": {"ol_shibuya": {"rows_test": 100, "overall": {"total_mae": 17.0}}},
    }
    cache_dir = tmp_path / "ml_models"
    cache_dir.mkdir()
    (cache_dir / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    monkeypatch.setenv("FORECAST_MODEL_CACHE_DIR", str(cache_dir))
    app2 = create_app()

    urls: list[str] = []
    _mock_storage(
        monkeypatch,
        {
            "accuracy/scores/summary.json": {
                "nights": [
                    {
                        "night_date": "20260101",
                        "overall_live_mae": 6.0,
                        "overall_baseline_mae": 8.0,
                        "stores_scored": 1,
                    }
                ],
                "updated_at_utc": "2026-01-02T22:00:00Z",
            },
            "accuracy/scores/20260101.json": {
                "per_store": {
                    "shibuya": {
                        "live_mae": 11.78,
                        "live_baseline_mae": 22.29,
                        "realized_night_avg": 23.4,
                    }
                }
            },
        },
        urls,
    )
    client = app2.test_client()

    first = client.get("/api/forecast_accuracy")
    assert first.status_code == 200
    assert len(urls) == 2, "初回は summary.json と scores/<date>.json を1本ずつ"

    second = client.get("/api/forecast_accuracy")
    assert second.status_code == 200
    assert second.get_json()["live"] == first.get_json()["live"], "同じ結果を返す"
    assert len(urls) == 2, "2回目は Storage を叩かない"
