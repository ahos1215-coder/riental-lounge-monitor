"""番犬: ForecastService が返すエラー dict の形（error コード・キー集合・extra_meta）を固定する。

routes/forecast.py の `_error_status()` はこの error 値だけを見て HTTP ステータスを
決める（model_schema_mismatch/model_unavailable→503、forecast_internal_error→500、
supabase_error→200）。コード名が変わると監視とフロントの分岐が黙って壊れる。
"""

from __future__ import annotations

import logging

import pytest

from oriental.data.provider import SupabaseError
from oriental.ml.forecast_service import ForecastService
from oriental.ml.model_registry import ModelRegistryError, ModelSchemaMismatchError


class _RaisingProvider:
    def __init__(self, exc: Exception):
        self.logger = logging.getLogger("test")
        self._exc = exc

    def get_records(self, store_id: str, **_kwargs):
        raise self._exc


def _service(exc: Exception) -> ForecastService:
    return ForecastService(
        provider=_RaisingProvider(exc),
        timezone="Asia/Tokyo",
        backend="supabase",
        history_days=1,
        history_limit=10,
    )


@pytest.mark.parametrize(
    "exc, expected_error",
    [
        (SupabaseError("boom"), "supabase_error"),
        (ModelSchemaMismatchError("v6 != v7"), "model_schema_mismatch"),
        (ModelRegistryError("no model"), "model_unavailable"),
        (RuntimeError("unexpected"), "forecast_internal_error"),
    ],
)
def test_例外ごとのerrorコードが変わらない(exc, expected_error):
    result = _service(exc).forecast_next_hour(store_id="ol_test", freq_min=15)
    assert result["ok"] is False
    assert result["error"] == expected_error
    assert result["detail"] == str(exc)
    assert result["store"] == "ol_test"
    assert result["freq_min"] == 15
    assert result["data"] == []
    assert set(result.keys()) == {"ok", "error", "detail", "store", "freq_min", "data"}


def test_forecast_todayのエラーにはstart_h_end_hが載る():
    result = _service(SupabaseError("boom")).forecast_today(
        store_id="ol_test", freq_min=15, start_h=19, end_h=5
    )
    assert result["error"] == "supabase_error"
    assert result["start_h"] == 19
    assert result["end_h"] == 5
