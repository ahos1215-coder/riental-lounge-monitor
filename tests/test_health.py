"""番犬: `/healthz` が「本当に壊れているときに ok:false を返す」ことを固定する。

2026-09-09 の Supabase egress 枯渇事故（全リクエストが HTTP 402・収集も予測も日報も全滅）で
`/healthz` は3日半ずっと `{"ok": true}` を返し続け、外形監視5経路すべてが緑のままだった。
原因は payload の `ok` が定数 True だったこと。ここでは次を固定する:

  1. 正常時は ok:true（誤検知でオオカミ少年にしない）
  2. 予測モデルが1店もロードできていなければ ok:false
  3. 上流(Supabase)が 402/401/403 を返したら ok:false かつ**原因が payload に載る**
     （監視の通知本文に原因を書けるようにするのが今回の主目的）
  4. データが明らかに古ければ ok:false
  5. それでも **HTTP ステータスは常に 200**（UptimeRobot の暖機と、リポジトリから
     確認できない Render のヘルスチェック設定を壊さないため。詳細は health.py の docstring）

2026-09-09 のレビューで足した検問（下の方にまとめてある）:

  6. `/healthz` は public・無認証・レート制限対象外なので、**上流のホスト名・URL・
     スキーマ（テーブル名/列名）を payload に出さない**
  7. `/readyz` の 503 は**自然復旧しない原因に限る**（瞬断で本番を再起動させない）
  8. 「1店でもロードできていれば ok」の取りこぼし（42店中41店失敗）を塞ぐ

いずれのテストも Supabase へは出ない（`HTTP_SESSION` をフェイクに差し替えるか、資格情報を空にする）。
素の requests が呼ばれたら `_no_real_http` フィクスチャがその場で落とす。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
import requests

from oriental import create_app
from oriental.routes import health as health_mod
from oriental.utils.stores import ALL_STORE_IDS


@pytest.fixture(autouse=True)
def _no_real_http(monkeypatch):
    """このファイルのテストを絶対に外へ出さない（実接続する番犬は害になる）。

    2026-09-09 の事故中、本番 Supabase は全リクエストに 402 を返していた。実接続する
    テストが1つでも混ざっていると **本番が壊れているときにテストまで赤くなる** ——
    直そうとしている最中にだけ壊れる番犬になってしまい、切り分けの邪魔にしかならない。
    上流の応答は必ず `_FakeSession` で与える。素の requests が呼ばれたらここで落として、
    「うっかり実接続」をその場で気づけるようにする。
    """

    def _blocked(*_args, **_kwargs):  # pragma: no cover - 呼ばれたら即失敗させるため
        raise AssertionError(
            "tests/test_health.py must not perform real HTTP requests "
            "(use _FakeSession instead)"
        )

    monkeypatch.setattr(requests.sessions.Session, "request", _blocked)

# ---------------------------------------------------------------------------
# フェイク（外へ出ないためのもの）
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, *, ok: bool = True, status_code: int = 200, payload=None, bad_json: bool = False):
        self.ok = ok
        self.status_code = status_code
        self._payload = payload
        self._bad_json = bad_json

    def json(self):
        if self._bad_json:
            raise ValueError("not json")
        return self._payload


class _FakeSession:
    """`session.get(...)` だけを持つ最小のフェイク（呼ばれた回数を数える）。"""

    def __init__(self, response: _FakeResponse | None = None, exc: Exception | None = None):
        self._response = response
        self._exc = exc
        self.calls = 0

    def get(self, url, params=None, headers=None, timeout=None):  # noqa: D102
        self.calls += 1
        if self._exc is not None:
            raise self._exc
        return self._response


class _FakeModelRegistry:
    """ForecastModelRegistry.current_status() の代わりに固定の辞書を返すフェイク。

    Fable監査 Batch B5 bug#7: current_status() が trained_at_min/trained_at_max +
    loaded_store_count を追加で返すようになった (既存キーは維持)。/healthz が
    その追加キーをそのまま透過することを確認する。
    """

    def __init__(self, status: dict):
        self._status = status

    def current_status(self) -> dict:
        return self._status


class _FakeForecastService:
    def __init__(self, registry: _FakeModelRegistry):
        self.model_registry = registry


def _loaded_status(**overrides) -> dict:
    status = {
        "loaded": True,
        "stores_loaded": ["ol_a", "ol_b"],
        "loaded_store_count": 2,
        "refresh_sec": 900,
        "next_refresh_in_sec": 300,
        "schema_version": "v7",
        "trained_at": "2026-09-09T05:30:00+00:00",
        "trained_at_min": "2026-09-09T05:30:00+00:00",
        "trained_at_max": "2026-09-09T05:30:00+00:00",
        "loaded_at_unix": 1.0,
        "age_sec": 1.0,
        "last_refresh_ok_unix": 1.0,
        "last_error": None,
        "last_error_at_unix": None,
    }
    status.update(overrides)
    return status


def _base_env(monkeypatch) -> None:
    """テストを外部に出さない・時刻に依存させないための共通 env。"""
    monkeypatch.setenv("DISABLE_MODEL_PRELOAD", "1")  # preload スレッドを起こさない
    monkeypatch.setenv("HEALTH_FRESHNESS_TTL_SEC", "0")  # 既定の TTL キャッシュを切る
    monkeypatch.setenv("SUPABASE_URL", "")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "")


def _with_supabase(monkeypatch) -> None:
    """資格情報「あり」の状態にする（実在しないホスト。HTTP_SESSION はフェイクに差し替える）。"""
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-key")


def _app_with_session(monkeypatch, session: _FakeSession, *, model_loaded: bool = True):
    app = create_app()
    app.config["HTTP_SESSION"] = session
    if model_loaded:
        app.config["FORECAST_SERVICE"] = _FakeForecastService(_FakeModelRegistry(_loaded_status()))
    # 収集ウィンドウ判定は実時刻依存なので、既定では「ウィンドウ内」に固定する。
    monkeypatch.setattr(
        health_mod.timeutil, "collection_window", lambda **_kw: (True, None, None)
    )
    return app


def _iso_ago(seconds: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# 正常系
# ---------------------------------------------------------------------------


def test_healthz_ok(monkeypatch):
    """資格情報なし（＝ローカル/テスト）は「異常ではない」。ok:true のまま。"""
    _base_env(monkeypatch)
    client = create_app().test_client()
    resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body and body.get("ok") is True
    assert body["problems"] == []
    assert body["problem_detail"] == ""
    assert body["data_freshness"]["reason"] == "not_configured"


def test_healthz_ok_when_model_loaded_and_data_fresh(monkeypatch):
    """モデルがロード済み・データも新しければ ok:true（正常時に赤くしない）。"""
    _base_env(monkeypatch)
    _with_supabase(monkeypatch)
    session = _FakeSession(_FakeResponse(payload=[{"ts": _iso_ago(120)}]))
    client = _app_with_session(monkeypatch, session).test_client()

    body = client.get("/healthz").get_json()
    assert body["ok"] is True
    assert body["problems"] == []
    freshness = body["data_freshness"]
    assert freshness["reason"] == "ok"
    assert freshness["available"] is True
    assert freshness["stale"] is False
    assert freshness["stale_hard"] is False


# ---------------------------------------------------------------------------
# 異常系: 予測モデル
# ---------------------------------------------------------------------------


def test_healthz_ng_when_no_model_loaded(monkeypatch):
    """予測が有効・preload も有効・猶予も過ぎたのに1店もロードできていない → ok:false。

    2026-09-09 の事故そのもの（Supabase 402 で42店すべての preload が失敗し続けた）。
    """
    _base_env(monkeypatch)
    monkeypatch.setenv("ENABLE_FORECAST", "1")
    app = create_app()  # ここではまだ DISABLE_MODEL_PRELOAD=1 なので preload スレッドは起きない
    # 判定の条件だけを本番と同じにする（preload 有効・起動猶予ゼロ）
    monkeypatch.delenv("DISABLE_MODEL_PRELOAD", raising=False)
    monkeypatch.setenv("HEALTH_MODEL_GRACE_SEC", "0")

    resp = app.test_client().get("/healthz")
    body = resp.get_json()
    assert resp.status_code == 200  # ★ HTTP は 200 のまま（暖機とヘルスチェックを壊さない）
    assert body["ok"] is False
    assert "forecast_model_not_loaded" in body["problems"]
    assert "forecast_model_not_loaded" in body["problem_detail"]


def test_healthz_ok_during_startup_grace(monkeypatch):
    """起動直後の猶予中はモデル未ロードでも ok:true（毎デプロイ直後に赤くしない）。"""
    _base_env(monkeypatch)
    monkeypatch.setenv("ENABLE_FORECAST", "1")
    app = create_app()
    monkeypatch.delenv("DISABLE_MODEL_PRELOAD", raising=False)
    monkeypatch.setenv("HEALTH_MODEL_GRACE_SEC", "999999")  # まだ猶予中という扱い

    body = app.test_client().get("/healthz").get_json()
    assert body["ok"] is True
    assert body["problems"] == []


def test_healthz_ok_when_forecast_disabled(monkeypatch):
    """ENABLE_FORECAST=0 なら未ロードは正常（判定しない）。"""
    _base_env(monkeypatch)
    monkeypatch.setenv("ENABLE_FORECAST", "0")
    monkeypatch.setenv("HEALTH_MODEL_GRACE_SEC", "0")
    body = create_app().test_client().get("/healthz").get_json()
    assert body["ok"] is True
    assert body["problems"] == []


# ---------------------------------------------------------------------------
# 異常系: 上流(Supabase)
# ---------------------------------------------------------------------------


def test_healthz_ng_and_reports_cause_on_402(monkeypatch):
    """402（課金枠の枯渇）は ok:false にし、**原因を payload に残す**。

    監視スクリプトが通知本文に原因を書けることが目的。2026-09-09 の事故では
    通知の出口が GitHub の失敗メールだけで、原因が一文字も載っていなかった。
    """
    _base_env(monkeypatch)
    _with_supabase(monkeypatch)
    session = _FakeSession(
        _FakeResponse(ok=False, status_code=402, payload={"message": "exceed_cached_egress_quota"})
    )
    resp = _app_with_session(monkeypatch, session).test_client().get("/healthz")
    body = resp.get_json()

    assert resp.status_code == 200  # ★ 200 は維持
    assert body["ok"] is False
    assert "data_upstream_payment_required" in body["problems"]
    freshness = body["data_freshness"]
    assert freshness["available"] is False
    assert freshness["reason"] == "upstream_error"
    assert freshness["upstream_status"] == 402
    assert freshness["upstream_message"] == "exceed_cached_egress_quota"
    # 通知本文にそのまま貼れる一文になっていること
    assert "402" in body["problem_detail"]
    assert "exceed_cached_egress_quota" in body["problem_detail"]


def test_healthz_distinguishes_auth_from_billing(monkeypatch):
    """401/403（資格情報の失効）は 402 とは別コードで出す（通知の文面を変えられるように）。"""
    _base_env(monkeypatch)
    _with_supabase(monkeypatch)
    session = _FakeSession(_FakeResponse(ok=False, status_code=401, payload={"message": "invalid api key"}))
    body = _app_with_session(monkeypatch, session).test_client().get("/healthz").get_json()
    assert body["ok"] is False
    assert "data_upstream_unauthorized" in body["problems"]


def test_healthz_non_json_error_body_is_not_leaked(monkeypatch):
    """JSON でないエラーボディ（HTML など）は本文を載せない。ステータスだけ出す。"""
    _base_env(monkeypatch)
    _with_supabase(monkeypatch)
    session = _FakeSession(_FakeResponse(ok=False, status_code=503, bad_json=True))
    body = _app_with_session(monkeypatch, session).test_client().get("/healthz").get_json()
    assert body["ok"] is False
    assert body["problems"] == ["data_upstream_error"]
    assert body["data_freshness"]["upstream_status"] == 503
    assert body["data_freshness"]["upstream_message"] is None


def test_healthz_ng_when_upstream_unreachable(monkeypatch):
    """到達不能・タイムアウトは 402 とは別に「data_unreachable」として出す。"""
    _base_env(monkeypatch)
    _with_supabase(monkeypatch)
    session = _FakeSession(exc=TimeoutError("connect timeout"))
    body = _app_with_session(monkeypatch, session).test_client().get("/healthz").get_json()
    assert body["ok"] is False
    assert body["problems"] == ["data_unreachable"]
    assert body["data_freshness"]["reason"] == "request_failed"
    assert "TimeoutError" in body["data_freshness"]["upstream_message"]


# ---------------------------------------------------------------------------
# 異常系: データ鮮度
# ---------------------------------------------------------------------------


def test_healthz_ng_when_data_stale_in_collection_window(monkeypatch):
    """収集ウィンドウ内で30分以上更新が無ければ ok:false。"""
    _base_env(monkeypatch)
    _with_supabase(monkeypatch)
    session = _FakeSession(_FakeResponse(payload=[{"ts": _iso_ago(3600)}]))
    body = _app_with_session(monkeypatch, session).test_client().get("/healthz").get_json()
    assert body["ok"] is False
    assert body["problems"] == ["data_stale"]
    assert body["data_freshness"]["stale"] is True


def test_healthz_ng_when_data_obviously_old_outside_window(monkeypatch):
    """ウィンドウ外でも「明らかに古い」（既定24時間超）なら ok:false。

    旧実装の盲点。収集は 2026-09-06 07:00 JST に止まったが、収集ウィンドウ
    (19:00-05:00) の外では stale 判定が働かないため、昼の時間帯は何日止まっていても
    緑のままだった。
    """
    _base_env(monkeypatch)
    _with_supabase(monkeypatch)
    session = _FakeSession(_FakeResponse(payload=[{"ts": _iso_ago(3 * 86400)}]))
    app = _app_with_session(monkeypatch, session)
    monkeypatch.setattr(health_mod.timeutil, "collection_window", lambda **_kw: (False, None, None))

    body = app.test_client().get("/healthz").get_json()
    assert body["ok"] is False
    assert body["problems"] == ["data_too_old"]
    assert body["data_freshness"]["stale"] is False  # ウィンドウ外なので従来の stale は立たない
    assert body["data_freshness"]["stale_hard"] is True


def test_healthz_ng_when_logs_empty(monkeypatch):
    """logs が0件（テーブルが空・権限で見えない等）も異常として出す。"""
    _base_env(monkeypatch)
    _with_supabase(monkeypatch)
    session = _FakeSession(_FakeResponse(payload=[]))
    body = _app_with_session(monkeypatch, session).test_client().get("/healthz").get_json()
    assert body["ok"] is False
    assert body["problems"] == ["data_missing"]


# ---------------------------------------------------------------------------
# レスポンス形状 / 既存フィールドの後方互換
# ---------------------------------------------------------------------------


_FRESHNESS_KEYS = {
    "available",
    "age_sec",
    "latest_ts",
    "stale",
    "stale_hard",
    "in_collection_window",
    "reason",
    "upstream_status",
    "upstream_message",
}


def test_data_freshness_keys_are_stable(monkeypatch):
    """成功・失敗のどちらでも data_freshness のキー集合が同じ（監視側が分岐しないで済む）。"""
    _base_env(monkeypatch)
    _with_supabase(monkeypatch)

    ok_session = _FakeSession(_FakeResponse(payload=[{"ts": _iso_ago(60)}]))
    ok_body = _app_with_session(monkeypatch, ok_session).test_client().get("/healthz").get_json()
    assert set(ok_body["data_freshness"].keys()) == _FRESHNESS_KEYS

    ng_session = _FakeSession(_FakeResponse(ok=False, status_code=402, payload={"message": "x"}))
    ng_body = _app_with_session(monkeypatch, ng_session).test_client().get("/healthz").get_json()
    assert set(ng_body["data_freshness"].keys()) == _FRESHNESS_KEYS


def test_healthz_keeps_rate_limit_instrument(monkeypatch):
    """レート制限の計器（2026-08-21 に足したもの）を壊していないこと。"""
    _base_env(monkeypatch)
    monkeypatch.setenv("API_RATE_LIMIT_ENABLED", "1")
    body = create_app().test_client().get("/healthz").get_json()
    assert body["api_rate_limit"]["enabled"] is True
    assert body["api_rate_limit"]["per_min"] >= 1
    assert "tracked_keys" in body["api_rate_limit"]


def test_healthz_has_memory_key(monkeypatch):
    """/healthz は memory.rss_mb を必ず返す（追加フィールド。取得不能環境では None）。"""
    _base_env(monkeypatch)
    app = create_app()
    client = app.test_client()
    body = client.get("/healthz").get_json()
    assert "memory" in body
    assert "rss_mb" in body["memory"]
    rss = body["memory"]["rss_mb"]
    assert rss is None or (isinstance(rss, (int, float)) and rss > 0)


def test_memory_status_warns_over_threshold(monkeypatch, caplog):
    """rss_mb が MEMORY_WARN_MB を超えたら WARNING を出す（OOM 予兆の監視シグナル）。"""
    import logging

    _base_env(monkeypatch)
    monkeypatch.setenv("MEMORY_WARN_MB", "1")  # 極小しきい値で必ず超過させる
    monkeypatch.setattr(health_mod, "_process_rss_mb", lambda: 123.4)

    app = create_app()
    with app.app_context(), caplog.at_level(logging.WARNING):
        status = health_mod._memory_status()

    assert status == {"rss_mb": 123.4}
    assert any("health.memory_high" in rec.message for rec in caplog.records)


def test_memory_pressure_does_not_flip_ok(monkeypatch):
    """メモリ逼迫は「予兆」であって障害ではない → ok は倒さない（常時赤を作らない）。"""
    _base_env(monkeypatch)
    monkeypatch.setenv("MEMORY_WARN_MB", "1")
    monkeypatch.setattr(health_mod, "_process_rss_mb", lambda: 999.9)
    body = create_app().test_client().get("/healthz").get_json()
    assert body["ok"] is True
    assert body["memory"]["rss_mb"] == 999.9


def test_healthz_forecast_model_reports_trained_at_min_max_and_loaded_count(monkeypatch):
    """/healthz の forecast_model は additive keys (trained_at_min/max, loaded_store_count)
    を透過しつつ、既存キー (schema_version, trained_at, stores_loaded 等) も壊さない。"""
    _base_env(monkeypatch)
    app = create_app()

    fake_status = _loaded_status(
        trained_at="2026-07-16T05:30:00+00:00",
        trained_at_min="2026-07-16T05:30:00+00:00",
        trained_at_max="2026-07-17T05:30:00+00:00",
    )
    app.config["FORECAST_SERVICE"] = _FakeForecastService(_FakeModelRegistry(fake_status))

    client = app.test_client()
    body = client.get("/healthz").get_json()
    fm = body["forecast_model"]

    # 追加キー: 伝播が滞留している店舗があれば min != max で見える
    assert fm["loaded_store_count"] == 2
    assert fm["trained_at_min"] == "2026-07-16T05:30:00+00:00"
    assert fm["trained_at_max"] == "2026-07-17T05:30:00+00:00"
    # 既存キーは維持（後方互換）
    assert fm["schema_version"] == "v7"
    assert fm["trained_at"] == "2026-07-16T05:30:00+00:00"
    assert fm["stores_loaded"] == ["ol_a", "ol_b"]
    assert fm["loaded"] is True


# ---------------------------------------------------------------------------
# TTL キャッシュ（/healthz はレート制限の対象外なので、連打で上流を増幅させない）
# ---------------------------------------------------------------------------


def test_freshness_is_cached_within_ttl(monkeypatch):
    _base_env(monkeypatch)
    _with_supabase(monkeypatch)
    monkeypatch.setenv("HEALTH_FRESHNESS_TTL_SEC", "30")
    session = _FakeSession(_FakeResponse(payload=[{"ts": _iso_ago(60)}]))
    client = _app_with_session(monkeypatch, session).test_client()

    for _ in range(5):
        assert client.get("/healthz").status_code == 200
    assert session.calls == 1  # 上流への問い合わせは1回だけ


def test_freshness_cache_can_be_disabled(monkeypatch):
    _base_env(monkeypatch)  # HEALTH_FRESHNESS_TTL_SEC=0
    _with_supabase(monkeypatch)
    session = _FakeSession(_FakeResponse(payload=[{"ts": _iso_ago(60)}]))
    client = _app_with_session(monkeypatch, session).test_client()

    client.get("/healthz")
    client.get("/healthz")
    assert session.calls == 2


# ---------------------------------------------------------------------------
# /readyz との役割分担
# ---------------------------------------------------------------------------


def test_readyz_returns_503_when_model_not_loaded(monkeypatch):
    """/readyz は従来どおり厳しい（起動猶予も ENABLE_FORECAST も見ずに未ロード＝503）。"""
    _base_env(monkeypatch)
    resp = create_app().test_client().get("/readyz")
    assert resp.status_code == 503
    body = resp.get_json()
    assert body["ok"] is False
    assert "forecast_model_not_loaded" in body["problems"]


def test_readyz_returns_503_on_upstream_402(monkeypatch):
    """モデルがロード済みでも、上流が 402 なら実トラフィックはさばけない → 503。"""
    _base_env(monkeypatch)
    _with_supabase(monkeypatch)
    session = _FakeSession(_FakeResponse(ok=False, status_code=402, payload={"message": "quota"}))
    resp = _app_with_session(monkeypatch, session).test_client().get("/readyz")
    assert resp.status_code == 503
    assert "data_upstream_payment_required" in resp.get_json()["problems"]


def test_readyz_200_when_healthy(monkeypatch):
    _base_env(monkeypatch)
    _with_supabase(monkeypatch)
    session = _FakeSession(_FakeResponse(payload=[{"ts": _iso_ago(60)}]))
    resp = _app_with_session(monkeypatch, session).test_client().get("/readyz")
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    assert resp.get_json()["blocking_problems"] == []


# ---------------------------------------------------------------------------
# 情報漏れ（/healthz は public・無認証・レート制限対象外）
# ---------------------------------------------------------------------------


def test_healthz_does_not_leak_upstream_host_or_url_on_exception(monkeypatch):
    """例外文字列にホスト名・URL が含まれていても payload に出さない（型名だけ）。

    requests の接続系例外は本番だと
      HTTPSConnectionPool(host='<project-ref>.supabase.co', port=443): Max retries
      exceeded with url: /rest/v1/logs?select=ts&order=ts.desc&limit=1
    のように、Supabase プロジェクトのホスト名と REST のパス・クエリをそのまま含む。
    誰でも叩ける口に「枯渇させられる相手先」を書かないための検問。
    """
    _base_env(monkeypatch)
    _with_supabase(monkeypatch)
    leaky = requests.exceptions.ConnectionError(
        "HTTPSConnectionPool(host='abcdefghijklmnop.supabase.co', port=443): "
        "Max retries exceeded with url: /rest/v1/logs?select=ts&order=ts.desc&limit=1 "
        "(Caused by NewConnectionError(...))"
    )
    session = _FakeSession(exc=leaky)
    body = _app_with_session(monkeypatch, session).test_client().get("/healthz").get_json()

    # 異常であること自体は従来どおり伝わる
    assert body["ok"] is False
    assert body["problems"] == ["data_unreachable"]
    # 型名だけ = 切り分けには足りるが、相手先は分からない
    assert body["data_freshness"]["upstream_message"] == "ConnectionError"

    blob = json.dumps(body, ensure_ascii=False)
    for secret in ("supabase.co", "abcdefghijklmnop", "/rest/v1/logs", "select=ts", "port=443"):
        assert secret not in blob, f"/healthz が {secret!r} を漏らしている"


def test_readyz_does_not_leak_upstream_host_or_url_on_exception(monkeypatch):
    """/readyz も同じ payload 組み立てを通るので、同じ検問をかける。"""
    _base_env(monkeypatch)
    _with_supabase(monkeypatch)
    session = _FakeSession(
        exc=requests.exceptions.ReadTimeout(
            "HTTPSConnectionPool(host='abcdefghijklmnop.supabase.co', port=443): "
            "Read timed out. url: /rest/v1/logs?select=ts"
        )
    )
    body = _app_with_session(monkeypatch, session).test_client().get("/readyz").get_json()
    blob = json.dumps(body, ensure_ascii=False)
    for secret in ("supabase.co", "abcdefghijklmnop", "/rest/v1/logs"):
        assert secret not in blob, f"/readyz が {secret!r} を漏らしている"


def test_healthz_does_not_leak_postgrest_hint_or_code(monkeypatch):
    """PostgREST の `hint` / `code` は載せない（列名・テーブル名が漏れるため）。

    `message` が無いエラー応答では upstream_message は None（ステータスだけ）になる。
    """
    _base_env(monkeypatch)
    _with_supabase(monkeypatch)
    session = _FakeSession(
        _FakeResponse(
            ok=False,
            status_code=400,
            payload={
                "code": "42703",
                "details": None,
                "hint": 'Perhaps you meant to reference the column "logs.ts_utc".',
            },
        )
    )
    body = _app_with_session(monkeypatch, session).test_client().get("/healthz").get_json()

    assert body["ok"] is False
    assert body["problems"] == ["data_upstream_error"]
    assert body["data_freshness"]["upstream_status"] == 400
    assert body["data_freshness"]["upstream_message"] is None

    blob = json.dumps(body, ensure_ascii=False)
    for secret in ("ts_utc", "42703", "Perhaps you meant"):
        assert secret not in blob, f"/healthz が {secret!r} を漏らしている"


def test_healthz_keeps_message_but_drops_hint(monkeypatch):
    """`message` があるときは従来どおり原因を載せる（同居する hint は載せない）。"""
    _base_env(monkeypatch)
    _with_supabase(monkeypatch)
    session = _FakeSession(
        _FakeResponse(
            ok=False,
            status_code=402,
            payload={
                "message": "exceed_cached_egress_quota",
                "hint": 'column "logs.ts_utc" does not exist',
            },
        )
    )
    body = _app_with_session(monkeypatch, session).test_client().get("/healthz").get_json()
    assert body["data_freshness"]["upstream_message"] == "exceed_cached_egress_quota"
    assert "ts_utc" not in json.dumps(body, ensure_ascii=False)


# ---------------------------------------------------------------------------
# /readyz の 503 は「自然復旧しない原因」に限る（瞬断で本番を再起動させない）
# ---------------------------------------------------------------------------


def test_readyz_stays_200_on_transient_request_failure(monkeypatch):
    """到達不能・タイムアウトでは 503 にしない（healthz は ok:false のまま）。

    `ConfiguredSession` は Retry(total=3, backoff=0.6) を持つので、ネットワークの
    1回の瞬断でも約24秒かけて必ず request_failed に落ちる。しかも 30 秒 TTL キャッシュに
    乗るため 503 が最大30秒続く。Render のヘルスチェックが /readyz を見ていた場合、
    Supabase の瞬断だけでインスタンス再起動＝サイト全落ちになる。
    """
    _base_env(monkeypatch)
    _with_supabase(monkeypatch)
    session = _FakeSession(exc=TimeoutError("connect timeout"))
    app = _app_with_session(monkeypatch, session)

    resp = app.test_client().get("/readyz")
    assert resp.status_code == 200  # ★ 切り離さない
    body = resp.get_json()
    assert body["ok"] is True
    # ただし「見えなくなった」わけではない: 異常自体は problems に載る
    assert body["problems"] == ["data_unreachable"]
    assert body["blocking_problems"] == []

    # 同じ状態で /healthz は従来どおり ok:false（監視には届く）
    assert app.test_client().get("/healthz").get_json()["ok"] is False


def test_readyz_stays_200_on_upstream_5xx(monkeypatch):
    """上流の 5xx も一過性。402/401/403 と違って待てば戻るので 503 にしない。"""
    _base_env(monkeypatch)
    _with_supabase(monkeypatch)
    session = _FakeSession(_FakeResponse(ok=False, status_code=503, payload={"message": "upstream busy"}))
    resp = _app_with_session(monkeypatch, session).test_client().get("/readyz")
    assert resp.status_code == 200
    assert resp.get_json()["problems"] == ["data_upstream_error"]
    assert resp.get_json()["blocking_problems"] == []


def test_readyz_still_503_on_persistent_causes(monkeypatch):
    """自然復旧しない原因（401・データが明らかに古い）では従来どおり 503。"""
    _base_env(monkeypatch)
    _with_supabase(monkeypatch)

    unauthorized = _FakeSession(_FakeResponse(ok=False, status_code=401, payload={"message": "invalid api key"}))
    resp = _app_with_session(monkeypatch, unauthorized).test_client().get("/readyz")
    assert resp.status_code == 503
    assert resp.get_json()["blocking_problems"] == ["data_upstream_unauthorized"]

    too_old = _FakeSession(_FakeResponse(payload=[{"ts": _iso_ago(3 * 86400)}]))
    app = _app_with_session(monkeypatch, too_old)
    monkeypatch.setattr(health_mod.timeutil, "collection_window", lambda **_kw: (False, None, None))
    resp = app.test_client().get("/readyz")
    assert resp.status_code == 503
    assert resp.get_json()["blocking_problems"] == ["data_too_old"]


# ---------------------------------------------------------------------------
# 「1店でもロードできていれば ok」の取りこぼし（42店中41店失敗）
# ---------------------------------------------------------------------------


def _app_judging_forecast_model(monkeypatch, status: dict):
    """モデルの判定条件（予測有効・preload 有効・起動猶予ゼロ）を本番と同じにした app。"""
    monkeypatch.setenv("ENABLE_FORECAST", "1")
    app = create_app()  # ここではまだ DISABLE_MODEL_PRELOAD=1 なので preload スレッドは起きない
    app.config["FORECAST_SERVICE"] = _FakeForecastService(_FakeModelRegistry(status))
    monkeypatch.delenv("DISABLE_MODEL_PRELOAD", raising=False)
    monkeypatch.setenv("HEALTH_MODEL_GRACE_SEC", "0")
    return app


def test_healthz_ng_when_most_stores_have_no_model(monkeypatch):
    """42店中1店しかロードできていなければ ok:false。

    `loaded` は「バンドルが1つでもあれば True」なので、これを見るだけでは
    41店 preload 失敗を丸ごと取りこぼしていた（2026-09-09 レビュー）。
    """
    _base_env(monkeypatch)
    status = _loaded_status(stores_loaded=["ol_shibuya"], loaded_store_count=1)
    body = _app_judging_forecast_model(monkeypatch, status).test_client().get("/healthz").get_json()

    assert body["ok"] is False
    assert body["problems"] == ["forecast_model_partially_loaded"]
    assert f"1/{len(ALL_STORE_IDS)}" in body["problem_detail"]


def test_healthz_ok_when_all_stores_loaded(monkeypatch):
    """全店ロードできていれば当然 ok:true（しきい値で正常を赤くしない）。"""
    _base_env(monkeypatch)
    status = _loaded_status(
        stores_loaded=list(ALL_STORE_IDS), loaded_store_count=len(ALL_STORE_IDS)
    )
    body = _app_judging_forecast_model(monkeypatch, status).test_client().get("/healthz").get_json()
    assert body["ok"] is True
    assert body["problems"] == []


def test_healthz_ok_when_a_few_stores_missing(monkeypatch):
    """数店だけ欠けている状態は正常扱い（新店・学習データ不足で欠けるのは普通）。

    「1店でも欠けたら赤」にすると常時赤い監視になり、今回の事故（誰も監視を見ていない）を
    再生産する。異常側に倒すのは「大半の店で予測が出ていない」ときだけ。
    """
    _base_env(monkeypatch)
    count = len(ALL_STORE_IDS) - 2
    status = _loaded_status(stores_loaded=list(ALL_STORE_IDS)[:count], loaded_store_count=count)
    body = _app_judging_forecast_model(monkeypatch, status).test_client().get("/healthz").get_json()
    assert body["ok"] is True
    assert body["problems"] == []


def test_partial_load_is_not_judged_while_preload_disabled(monkeypatch):
    """DISABLE_MODEL_PRELOAD=1（遅延ロード運用）では部分ロードは正常。

    最初の予測リクエストが来るまで1店もロードされていないのが正常な運用なので、
    ここで赤くすると誤検知になる（`loaded` の判定と同じ扱い）。
    """
    _base_env(monkeypatch)  # DISABLE_MODEL_PRELOAD=1 のまま
    monkeypatch.setenv("ENABLE_FORECAST", "1")
    monkeypatch.setenv("HEALTH_MODEL_GRACE_SEC", "0")
    app = create_app()
    app.config["FORECAST_SERVICE"] = _FakeForecastService(
        _FakeModelRegistry(_loaded_status(stores_loaded=["ol_shibuya"], loaded_store_count=1))
    )
    body = app.test_client().get("/healthz").get_json()
    assert body["ok"] is True
    assert body["problems"] == []


def test_partial_load_does_not_take_instance_out_of_rotation(monkeypatch):
    """部分ロードで /readyz を 503 にはしない。

    ロード済みの店は正常にさばけるので、切り離すと「さばけていた分」まで止まる。
    異常であることは /healthz と /readyz の problems で伝わる。
    """
    _base_env(monkeypatch)
    status = _loaded_status(stores_loaded=["ol_shibuya"], loaded_store_count=1)
    resp = _app_judging_forecast_model(monkeypatch, status).test_client().get("/readyz")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["problems"] == ["forecast_model_partially_loaded"]
    assert body["blocking_problems"] == []


def test_partial_load_threshold_is_tunable(monkeypatch):
    """しきい値は env で動かせる（誤検知時に即座に緩められる逃がし弁）。"""
    _base_env(monkeypatch)
    count = len(ALL_STORE_IDS) // 4  # 既定 0.5 なら異常、0.1 なら正常
    status = _loaded_status(stores_loaded=list(ALL_STORE_IDS)[:count], loaded_store_count=count)

    monkeypatch.setenv("HEALTH_MIN_LOADED_STORE_RATIO", "0.1")
    body = _app_judging_forecast_model(monkeypatch, status).test_client().get("/healthz").get_json()
    assert body["ok"] is True


def test_partial_load_not_judged_when_count_missing(monkeypatch):
    """`loaded_store_count` を持たない古い形の status では判定しない（分からないものは黙る）。"""
    _base_env(monkeypatch)
    status = _loaded_status()
    status.pop("loaded_store_count")
    body = _app_judging_forecast_model(monkeypatch, status).test_client().get("/healthz").get_json()
    assert body["ok"] is True
    assert body["problems"] == []
