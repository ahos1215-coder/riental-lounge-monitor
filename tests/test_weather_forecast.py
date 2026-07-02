"""oriental.ml.weather_forecast.get_hourly_forecast の単体テスト。

安全設計の検証が主眼:
  - 座標不明 -> {} を返し urlopen は呼ばれない
  - タイムアウト/パース失敗 -> 例外を外に出さず {} を返す
  - 正常系のキー整形 ("YYYY-MM-DDTHH" プレフィックス) と値のタプル化
  - 店舗単位 ~1時間キャッシュが実際に効く (urlopen が2回目は呼ばれない)
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from oriental.ml import weather_forecast


@pytest.fixture(autouse=True)
def _reset_state():
    """各テスト間でキャッシュ/座標キャッシュをクリアして独立性を保つ。"""
    weather_forecast._forecast_cache.clear()
    weather_forecast._coords_cache = None
    yield
    weather_forecast._forecast_cache.clear()
    weather_forecast._coords_cache = None


def _hourly_body(times, codes, temps, precs) -> bytes:
    payload = {
        "hourly": {
            "time": times,
            "weather_code": codes,
            "temperature_2m": temps,
            "precipitation": precs,
        }
    }
    return json.dumps(payload).encode("utf-8")


def _mock_urlopen_returning(body: bytes) -> MagicMock:
    """urllib.request.urlopen(...) は `with urlopen(...) as resp:` で使われるため、
    戻り値はコンテキストマネージャである必要がある。"""
    cm = MagicMock()
    cm.__enter__.return_value.read.return_value = body
    cm.__exit__.return_value = False
    mock_urlopen = MagicMock(return_value=cm)
    return mock_urlopen


def test_happy_path_returns_hour_keyed_tuples(monkeypatch):
    weather_forecast._coords_cache = {"ol_test": (35.0, 139.0)}
    body = _hourly_body(
        times=["2026-07-03T19:00", "2026-07-03T20:00", "2026-07-03T21:00"],
        codes=[1, 61, 3],
        temps=[28.5, 27.0, 26.2],
        precs=[0.0, 1.2, 0.0],
    )
    mock_urlopen = _mock_urlopen_returning(body)
    monkeypatch.setattr(weather_forecast.urllib.request, "urlopen", mock_urlopen)

    result = weather_forecast.get_hourly_forecast("ol_test")

    assert set(result.keys()) == {
        "2026-07-03T19",
        "2026-07-03T20",
        "2026-07-03T21",
    }
    for key in result:
        assert len(key) == 13
    assert result["2026-07-03T19"] == (1, 28.5, 0.0)
    assert result["2026-07-03T20"] == (61, 27.0, 1.2)
    assert result["2026-07-03T21"] == (3, 26.2, 0.0)


def test_unknown_store_returns_empty_and_skips_network(monkeypatch):
    weather_forecast._coords_cache = {"ol_test": (35.0, 139.0)}
    mock_urlopen = MagicMock()
    monkeypatch.setattr(weather_forecast.urllib.request, "urlopen", mock_urlopen)

    result = weather_forecast.get_hourly_forecast("ol_unknown_store")

    assert result == {}
    mock_urlopen.assert_not_called()


def test_timeout_returns_empty(monkeypatch):
    weather_forecast._coords_cache = {"ol_test": (35.0, 139.0)}

    def _raise_timeout(*args, **kwargs):
        raise TimeoutError("timed out")

    monkeypatch.setattr(weather_forecast.urllib.request, "urlopen", _raise_timeout)

    result = weather_forecast.get_hourly_forecast("ol_test")

    assert result == {}


def test_malformed_body_returns_empty(monkeypatch):
    weather_forecast._coords_cache = {"ol_test": (35.0, 139.0)}
    mock_urlopen = _mock_urlopen_returning(b"not json")
    monkeypatch.setattr(weather_forecast.urllib.request, "urlopen", mock_urlopen)

    result = weather_forecast.get_hourly_forecast("ol_test")

    assert result == {}


def test_cache_hit_within_ttl_skips_second_network_call(monkeypatch):
    weather_forecast._coords_cache = {"ol_test": (35.0, 139.0)}
    body = _hourly_body(
        times=["2026-07-03T19:00", "2026-07-03T20:00"],
        codes=[1, 2],
        temps=[28.0, 27.5],
        precs=[0.0, 0.0],
    )
    mock_urlopen = _mock_urlopen_returning(body)
    monkeypatch.setattr(weather_forecast.urllib.request, "urlopen", mock_urlopen)

    first = weather_forecast.get_hourly_forecast("ol_test")
    second = weather_forecast.get_hourly_forecast("ol_test")

    assert mock_urlopen.call_count == 1
    assert first == second
