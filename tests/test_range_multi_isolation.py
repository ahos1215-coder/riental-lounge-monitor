"""/api/range_multi の店舗別例外隔離のテスト（2026-08-22 総合レビュー対応。
検証記録は memory/general-review-2026-08-22.md）。

背景: data_range.py の api_range_multi は `for fut in as_completed(futures):
slug_key, data, cache_status = fut.result()` に try/except が無く、1店舗の
想定外例外（SupabaseError 以外——_deduplicate_by_ts / _trim_range_rows の
データ異常や SingleFlightTTLCache の raise 経路など）で fut.result() が
例外を投げると /api/range_multi 全体が Flask 500 になり、/stores 一覧ページの
主データ経路が丸ごと落ちていた。forecast.py の forecast_today_multi には既に
店舗別の try/except 隔離があり、その契約に揃える。

_FakeProvider.fetch_range() が SupabaseError ではなく素の Exception を投げる
ケースは、_compute_range_for_store 内の `except SupabaseError` では捕まらず
そのまま呼び出し元（ThreadPoolExecutor のワーカー）まで伝播する。これが
「想定外例外」の最小の再現。
"""

from __future__ import annotations

import pytest

from oriental import create_app


class _FakeProvider:
    """rows_by_store[store_id] が Exception インスタンスなら fetch_range() が
    それを投げる（SupabaseError 以外＝想定外例外の再現用）。"""

    def __init__(self, rows_by_store: dict | None = None):
        self.rows_by_store = rows_by_store or {}
        self.calls: list[str] = []

    def fetch_range(self, *, store_id, limit, start_ts=None, end_ts=None):
        self.calls.append(store_id)
        value = self.rows_by_store.get(store_id, [])
        if isinstance(value, Exception):
            raise value
        return list(value)


@pytest.fixture
def app_and_provider(monkeypatch):
    monkeypatch.setenv("DATA_BACKEND", "supabase")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-key")
    monkeypatch.setenv("DISABLE_MODEL_PRELOAD", "1")

    from oriental.routes import data_range as data_module

    provider = _FakeProvider(rows_by_store={
        "ol_gangnam": [
            {"ts": "2026-07-09T23:00:00+09:00", "men": 3, "women": 4, "total": 7},
        ],
        "ol_shibuya": RuntimeError("boom: unexpected data corruption"),
    })
    monkeypatch.setattr(data_module, "_supabase_provider", lambda cfg: provider)

    app = create_app()
    return app, provider


def test_one_store_unexpected_exception_does_not_break_whole_response(app_and_provider):
    """1店舗が想定外例外を投げても /api/range_multi は 200 で返り、他店舗は
    正常データ、当該店舗はエラーエントリになる（全体が Flask 500 にならない）。"""
    app, provider = app_and_provider
    client = app.test_client()

    resp = client.get(
        "/api/range_multi?stores=gangnam,shibuya&from=2026-07-01&to=2026-07-02"
    )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True

    # 正常だった店舗は普段どおりのデータを返す
    assert body["by_slug"]["gangnam"]["rows"] == [
        {"ts": "2026-07-09T23:00:00+09:00", "men": 3, "women": 4, "total": 7}
    ]

    # 例外を投げた店舗はエラーエントリ（rows は空、ok は False）になる
    assert body["by_slug"]["shibuya"]["ok"] is False
    assert body["by_slug"]["shibuya"]["rows"] == []
    assert body["by_slug"]["shibuya"]["error"] == "internal-error"

    # partial_failure_count は他店舗の失敗検出（既存の SupabaseError 系）と
    # 同じ集計に乗る
    assert body["partial_failure_count"] == 1


def test_all_stores_unexpected_exception_still_returns_200(app_and_provider):
    """全店舗が想定外例外でも、レスポンス自体は組み立てられて 200 で返る
    （フロントが die せず「一覧は空だがページは落ちない」状態を維持できる）。"""
    app, provider = app_and_provider
    provider.rows_by_store["ol_gangnam"] = RuntimeError("boom: also broken")

    client = app.test_client()
    resp = client.get(
        "/api/range_multi?stores=gangnam,shibuya&from=2026-07-01&to=2026-07-02"
    )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["by_slug"]["gangnam"]["ok"] is False
    assert body["by_slug"]["shibuya"]["ok"] is False
    assert body["partial_failure_count"] == 2
