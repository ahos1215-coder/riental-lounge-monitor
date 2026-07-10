"""URL マップ凍結テスト（回帰ガード）。

ルート定義をファイル分割・リファクタしても、外部に露出する URL / エンドポイント名 /
HTTP メソッドの集合が一切変わっていないことを保証する。B8 route split（data.py /
forecast.py を役割別モジュールへ機械分割）で導入。以後のリファクタも同じ保証を得られる。

期待値 EXPECTED_URL_MAP は origin/main（分割前）の
sorted([(rule, endpoint, sorted(methods))]) をそのまま凍結したもの。
url_map を意図的に変更した場合（ルート追加・削除等）は、その差分が本当に意図通りか
確認したうえでここを更新すること。
"""

from __future__ import annotations

from oriental import create_app

# origin/main（分割前）で dump した完全な url_map。static / health / tasks も含む。
EXPECTED_URL_MAP: list[list] = [
    ["/", "data.index", ["GET", "HEAD", "OPTIONS"]],
    ["/api/current", "data.api_current", ["GET", "HEAD", "OPTIONS"]],
    ["/api/forecast_accuracy", "forecast.api_forecast_accuracy", ["GET", "HEAD", "OPTIONS"]],
    ["/api/forecast_next_hour", "forecast.forecast_next_hour", ["GET", "HEAD", "OPTIONS"]],
    ["/api/forecast_snapshot", "forecast.api_forecast_snapshot", ["GET", "HEAD", "OPTIONS"]],
    ["/api/forecast_today", "forecast.forecast_today", ["GET", "HEAD", "OPTIONS"]],
    ["/api/forecast_today_multi", "forecast.forecast_today_multi", ["GET", "HEAD", "OPTIONS"]],
    ["/api/holiday_status", "data.api_holiday_status", ["GET", "HEAD", "OPTIONS"]],
    ["/api/megribi_score", "forecast.api_megribi_score", ["GET", "HEAD", "OPTIONS"]],
    ["/api/meta", "data.api_meta", ["GET", "HEAD", "OPTIONS"]],
    ["/api/range", "data.api_range", ["GET", "HEAD", "OPTIONS"]],
    ["/api/range_multi", "data.api_range_multi", ["GET", "HEAD", "OPTIONS"]],
    ["/api/second_venues", "data.api_second_venues", ["GET", "HEAD", "OPTIONS"]],
    ["/api/tasks/collect_all_once", "tasks.api_tasks_collect_all_once", ["GET", "HEAD", "OPTIONS", "POST"]],
    ["/healthz", "health.healthz", ["GET", "HEAD", "OPTIONS"]],
    ["/readyz", "health.readyz", ["GET", "HEAD", "OPTIONS"]],
    ["/static/<path:filename>", "static", ["GET", "HEAD", "OPTIONS"]],
    ["/tasks/collect", "tasks.tasks_collect_single", ["GET", "HEAD", "OPTIONS", "POST"]],
    ["/tasks/multi_collect", "tasks.tasks_multi_collect", ["GET", "HEAD", "OPTIONS", "POST"]],
    ["/tasks/multi_collect/status", "tasks.tasks_multi_collect_status", ["GET", "HEAD", "OPTIONS"]],
    ["/tasks/seed", "tasks.tasks_seed", ["GET", "HEAD", "OPTIONS"]],
    ["/tasks/tick", "tasks.tasks_tick", ["GET", "HEAD", "OPTIONS"]],
    ["/tasks/update_second_venues", "tasks.tasks_update_second_venues", ["GET", "HEAD", "OPTIONS", "POST"]],
]


def _dump_url_map() -> list[list]:
    app = create_app()
    return sorted(
        [str(rule), rule.endpoint, sorted(rule.methods)]
        for rule in app.url_map.iter_rules()
    )


def test_url_map_matches_frozen_snapshot(monkeypatch):
    """分割後の url_map が凍結スナップショットとバイト等価であること。"""
    monkeypatch.setenv("DISABLE_MODEL_PRELOAD", "1")
    assert _dump_url_map() == EXPECTED_URL_MAP


def test_split_handlers_registered_on_shared_blueprints(monkeypatch):
    """分割先モジュールのハンドラが、分割元と同じ Blueprint（data / forecast）に
    登録されていること（エンドポイント名の接頭辞で確認）。"""
    monkeypatch.setenv("DISABLE_MODEL_PRELOAD", "1")
    endpoints = {rule.endpoint for rule in create_app().url_map.iter_rules()}
    # data_range / data_meta のハンドラは "data." 接頭辞のまま
    assert {"data.api_current", "data.api_range", "data.api_range_multi"} <= endpoints
    assert {"data.api_meta", "data.api_holiday_status", "data.api_second_venues"} <= endpoints
    # forecast_accuracy のハンドラは "forecast." 接頭辞のまま
    assert {"forecast.api_forecast_accuracy", "forecast.api_forecast_snapshot"} <= endpoints
