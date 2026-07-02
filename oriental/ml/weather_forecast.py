"""推論時に未来（今夜）の行へ実天気「予報」を注入するための取得ユーティリティ。

train/serve skew の緩和:
  従来は preprocess.add_time_features が未来行の天気(weather_code/temp_c/precip_mm)を
  「直近の実測値の前方埋め(ffill)」で埋めるため、夜の間ずっと 18:10 時点の天気で固定され、
  is_rainy / precip_mm / extreme_weather / next_morning_rain / feat_rain_night_exit 等が
  凍結していた。ここで Open-Meteo の時間別"予報"を取得し未来行へ入れることで、これらの
  特徴が実際の見込みに沿って動き、雨/猛暑の夜の予測精度が改善する。

安全設計（最重要）:
  - 座標不明・取得失敗・タイムアウト・パース失敗は **すべて {} を返す**。呼び出し側は
    その場合 weather を NaN のままにするので、従来どおり ffill が働く＝**回帰なし**。
  - 例外は外に漏らさない（本関数は絶対に raise しない）。
  - 店舗ごと ~1 時間キャッシュ＋短いタイムアウトで、推論のレイテンシ増を最小化。
"""

from __future__ import annotations

import json
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, Optional, Tuple

# frontend/src/data/stores.json が全ブランドの store_id + lat/lon の単一ソース。
_STORES_JSON = Path(__file__).resolve().parents[2] / "frontend" / "src" / "data" / "stores.json"

_TTL_SEC = 3600  # 予報は 1 時間キャッシュ
_OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
_TIMEOUT = 6

_coords_cache: Optional[Dict[str, Tuple[float, float]]] = None
_forecast_cache: Dict[str, Tuple[float, Dict[str, Tuple]]] = {}
_lock = threading.Lock()


def _store_coords() -> Dict[str, Tuple[float, float]]:
    global _coords_cache
    if _coords_cache is None:
        result: Dict[str, Tuple[float, float]] = {}
        try:
            rows = json.loads(_STORES_JSON.read_text(encoding="utf-8"))
            for s in rows:
                sid = s.get("store_id")
                lat = s.get("lat")
                lon = s.get("lon")
                if sid and isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
                    result[sid] = (float(lat), float(lon))
        except Exception:
            result = {}
        _coords_cache = result
    return _coords_cache


def get_hourly_forecast(store_id: str, tz: str = "Asia/Tokyo") -> Dict[str, Tuple]:
    """store_id の座標で時間別予報を取得し {"YYYY-MM-DDTHH": (weather_code, temp_c, precip_mm)}
    を返す。座標不明・失敗時は {}（呼び出し側は NaN のまま＝現行 ffill 動作にフォールバック）。
    本関数は例外を外に出さない。"""
    try:
        coords = _store_coords().get(store_id)
        if not coords:
            return {}
        now = time.time()
        with _lock:
            cached = _forecast_cache.get(store_id)
            if cached and cached[0] > now:
                return cached[1]
        lat, lon = coords
        query = urllib.parse.urlencode(
            {
                "latitude": lat,
                "longitude": lon,
                "hourly": "weather_code,temperature_2m,precipitation",
                "timezone": tz,
                "forecast_days": 2,
            }
        )
        req = urllib.request.Request(
            f"{_OPEN_METEO}?{query}",
            headers={
                "User-Agent": "MEGRIBI-forecast/1.0 (weather; respectful use; open-meteo)",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        hourly = data.get("hourly") or {}
        times = hourly.get("time") or []
        codes = hourly.get("weather_code") or []
        temps = hourly.get("temperature_2m") or []
        precs = hourly.get("precipitation") or []
        out: Dict[str, Tuple] = {}
        for i, t in enumerate(times):
            key = str(t)[:13]  # "YYYY-MM-DDTHH"（時単位でマッチ）
            out[key] = (
                codes[i] if i < len(codes) else None,
                temps[i] if i < len(temps) else None,
                precs[i] if i < len(precs) else None,
            )
        if out:
            with _lock:
                _forecast_cache[store_id] = (now + _TTL_SEC, out)
        return out
    except Exception:
        return {}
