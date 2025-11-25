import logging

from oriental.data.provider import SupabaseError
from oriental.ml.forecast_service import ForecastService


class _FailingProvider:
    def __init__(self):
        self.logger = logging.getLogger("test")

    def get_records(self, store_id: str, **_kwargs):
        raise SupabaseError("boom")


class _FallbackProvider:
    def __init__(self):
        self.logger = logging.getLogger("test")
        self.called = False

    def get_records(self, store_id: str, **_kwargs):
        self.called = True
        return [{"ts": "2024-11-01T00:00:00Z", "men": 1, "women": 2, "total": 3}]


def test_forecast_supabase_error_surfaces_when_no_fallback():
    service = ForecastService(
        provider=_FailingProvider(),
        timezone="Asia/Tokyo",
        backend="supabase",
        history_days=1,
        history_limit=10,
    )

    result = service.forecast_next_hour(store_id="ol_test", freq_min=15)

    assert result["ok"] is False
    assert result["error"] == "supabase_error"


def test_forecast_supabase_fallback_uses_legacy_provider():
    failing = _FailingProvider()
    fallback = _FallbackProvider()
    service = ForecastService(
        provider=failing,
        fallback_provider=fallback,
        timezone="Asia/Tokyo",
        backend="supabase",
        history_days=1,
        history_limit=10,
    )

    result = service.forecast_next_hour(store_id="ol_test", freq_min=15)

    assert result["ok"] is True
    assert fallback.called is True
    assert isinstance(result.get("data"), list)
