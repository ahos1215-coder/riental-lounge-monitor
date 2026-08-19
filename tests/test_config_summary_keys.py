"""番犬: AppConfig.health_summary() / summary() のキー集合と共通部分の値を固定する。

/healthz と /api/meta のレスポンス契約そのもの。共通部分を `_shared_summary()` に
まとめても、両者のキー集合・値が1つも変わらないことを保証する
（キー順序には依存しない＝dict の比較で見る）。
"""

from __future__ import annotations

from oriental.config import AppConfig

_HEALTH_KEYS = {
    "store",
    "target",
    "gs_webhook",
    "gs_read",
    "timezone",
    "window",
    "data_backend",
    "supabase",
    "http_timeout",
    "http_retry",
    "max_range_limit",
    "forecast_model",
    "forecast_enabled",
}

_META_KEYS = {
    "store",
    "store_id",
    "data_backend",
    "supabase",
    "timezone",
    "window",
    "http_timeout",
    "http_retry",
    "max_range_limit",
    "forecast_model",
    "forecast_enabled",
}


def test_healthサマリのキー集合が変わらない():
    cfg = AppConfig.from_env()
    assert set(cfg.health_summary().keys()) == _HEALTH_KEYS


def test_metaサマリのキー集合が変わらない():
    cfg = AppConfig.from_env()
    assert set(cfg.summary().keys()) == _META_KEYS


def test_両サマリの共通キーは同じ値を返す():
    cfg = AppConfig.from_env()
    health = cfg.health_summary()
    meta = cfg.summary()
    for key in _HEALTH_KEYS & _META_KEYS:
        assert health[key] == meta[key], key


def test_forecast_modelブロックの中身が変わらない():
    cfg = AppConfig.from_env()
    expected = {
        "bucket": cfg.forecast_model_bucket,
        "prefix": cfg.forecast_model_prefix,
        "refresh_sec": cfg.forecast_model_refresh_sec,
        "schema_version": cfg.forecast_model_schema_version,
    }
    assert cfg.health_summary()["forecast_model"] == expected
    assert cfg.summary()["forecast_model"] == expected
    # supabase ブロックも両者で同一（store_id は summary のトップレベルにも出る）
    supabase = {
        "url": bool(cfg.supabase_url),
        "service_role": bool(cfg.supabase_service_role_key),
        "store_id": cfg.store_id,
    }
    assert cfg.health_summary()["supabase"] == supabase
    assert cfg.summary()["supabase"] == supabase
    assert cfg.summary()["store_id"] == cfg.store_id
