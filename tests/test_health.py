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
