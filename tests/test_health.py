from oriental import create_app


def test_healthz_ok():
    app = create_app()
    client = app.test_client()
    resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body and body.get("ok") is True


def test_healthz_has_memory_key(monkeypatch):
    """/healthz は memory.rss_mb を必ず返す（追加フィールド。取得不能環境では None）。"""
    monkeypatch.setenv("DISABLE_MODEL_PRELOAD", "1")
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

    from oriental.routes import health as health_mod

    monkeypatch.setenv("DISABLE_MODEL_PRELOAD", "1")
    monkeypatch.setenv("MEMORY_WARN_MB", "1")  # 極小しきい値で必ず超過させる
    monkeypatch.setattr(health_mod, "_process_rss_mb", lambda: 123.4)

    app = create_app()
    with app.app_context(), caplog.at_level(logging.WARNING):
        status = health_mod._memory_status()

    assert status == {"rss_mb": 123.4}
    assert any("health.memory_high" in rec.message for rec in caplog.records)


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


def test_healthz_forecast_model_reports_trained_at_min_max_and_loaded_count(monkeypatch):
    """/healthz の forecast_model は additive keys (trained_at_min/max, loaded_store_count)
    を透過しつつ、既存キー (schema_version, trained_at, stores_loaded 等) も壊さない。"""
    monkeypatch.setenv("DISABLE_MODEL_PRELOAD", "1")
    app = create_app()

    fake_status = {
        "loaded": True,
        "stores_loaded": ["ol_a", "ol_b"],
        "loaded_store_count": 2,
        "refresh_sec": 900,
        "next_refresh_in_sec": 300,
        "schema_version": "v7",
        "trained_at": "2026-07-16T05:30:00+00:00",
        "trained_at_min": "2026-07-16T05:30:00+00:00",
        "trained_at_max": "2026-07-17T05:30:00+00:00",
        "loaded_at_unix": 1.0,
        "age_sec": 1.0,
        "last_refresh_ok_unix": 1.0,
        "last_error": None,
        "last_error_at_unix": None,
    }
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
