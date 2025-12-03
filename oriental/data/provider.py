from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import requests
from dateutil import parser
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class DataProvider:
    def get_records(self, store_id: str, **kwargs: Any) -> list[dict]:
        raise NotImplementedError


class GoogleSheetProvider(DataProvider):
    def __init__(self, read_url: str, data_file: Path, *, logger: logging.Logger | None = None):
        self.read_url = read_url
        self.data_file = data_file
        self.logger = logger or logging.getLogger(__name__)
        self.session = requests.Session()
        retry = Retry(total=3, backoff_factor=0.6, status_forcelist=(429, 500, 502, 503, 504))
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def get_records(self, store_id: str, **_kwargs: Any) -> list[dict]:
        rows: list[dict] = []
        if self.read_url:
            try:
                resp = self.session.get(self.read_url, params={"store": store_id}, timeout=12)
                resp.raise_for_status()
                payload = resp.json()
                # Gracefully handle dict {"rows": [...]} responses to avoid str iteration errors.
                if isinstance(payload, list):
                    rows = payload
                elif isinstance(payload, dict):
                    rows = payload.get("rows", [])
                self.logger.info("forecast.provider.ok source=remote count=%d", len(rows))
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("forecast.provider.remote_failed", exc_info=exc)

        if not rows:
            try:
                rows = json.loads(self.data_file.read_text(encoding="utf-8-sig"))
                self.logger.info("forecast.provider.ok source=local count=%d", len(rows))
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("forecast.provider.local_failed", exc_info=exc)
                return []

        normalised = _normalise(rows, store_id)
        self.logger.debug("forecast.provider.normalised count=%d", len(normalised))
        return normalised


class SupabaseError(RuntimeError):
    """Raised when Supabase returns an error response."""


class SupabaseLogsProvider(DataProvider):
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        session: requests.Session | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/") if base_url else ""
        self.api_key = api_key
        self.endpoint = f"{self.base_url}/rest/v1/logs" if self.base_url else ""
        self.session = session or requests.Session()
        self.logger = logger or logging.getLogger(__name__)
        retry = Retry(total=3, backoff_factor=0.6, status_forcelist=(429, 500, 502, 503, 504))
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def fetch_range(
        self,
        *,
        store_id: str,
        limit: int,
        start_ts: datetime | None = None,
        end_ts: datetime | None = None,
    ) -> list[dict]:
        if not self.endpoint or not self.api_key:
            raise SupabaseError("supabase is not configured")
        if limit <= 0:
            return []

        # 最新を優先して取得するため Supabase には ts.desc で問い合わせる
        params: list[tuple[str, str]] = [
            ("select", "store_id,ts,men,women,total,weather_code,weather_label,temp_c,precip_mm,src_brand"),
            ("store_id", f"eq.{store_id}"),
            ("order", "ts.desc"),
            ("limit", str(limit)),
        ]
        if start_ts is not None:
            params.append(("ts", f"gte.{start_ts.isoformat()}"))
        if end_ts is not None:
            params.append(("ts", f"lte.{end_ts.isoformat()}"))
        headers = {
            "apikey": self.api_key,
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "Range-Unit": "items",
            "Range": f"0-{max(limit - 1, 0)}",
        }

        try:
            resp = self.session.get(self.endpoint, params=params, headers=headers, timeout=12)
        except Exception as exc:  # noqa: BLE001
            raise SupabaseError("supabase request failed") from exc

        if not resp.ok:
            raise SupabaseError(f"supabase returned status {resp.status_code}")

        try:
            payload = resp.json()
        except ValueError as exc:  # pragma: no cover - defensive
            raise SupabaseError("supabase returned invalid JSON") from exc

        if not isinstance(payload, list):
            raise SupabaseError("supabase payload is not a list")

        rows: list[dict] = []
        for row in payload:
            if not isinstance(row, dict):
                continue
            ts = row.get("ts")
            if not isinstance(ts, str):
                continue
            entry: dict[str, Any] = {
                "ts": ts,
                "men": _to_int(row.get("men")),
                "women": _to_int(row.get("women")),
                "total": _to_int(row.get("total")),
            }
            for extra in ("store_id", "weather_code", "weather_label", "temp_c", "precip_mm", "src_brand"):
                if extra in row:
                    entry[extra] = row.get(extra)
            rows.append(entry)

        # Supabase からは ts.desc（新しい順）で取得しているので、描画しやすいよう昇順に並べ替える
        rows.sort(key=lambda r: r.get("ts", ""))

        self.logger.info(
            "supabase.provider.fetch_range_ok store_id=%s returned=%d limit=%d",
            store_id,
            len(rows),
            limit,
        )
        return rows

    def get_records(self, store_id: str, *, days: int = 7, limit: int | None = None, **_kwargs: Any) -> list[dict]:
        """Fetch recent records for a store, defaulting to the last few days for forecasting."""
        end_ts = datetime.now(timezone.utc)
        start_ts = end_ts - timedelta(days=max(days, 1))
        fetch_limit = max(1, limit or 2000)
        return self.fetch_range(store_id=store_id, start_ts=start_ts, end_ts=end_ts, limit=fetch_limit)


def _normalise(rows: Iterable[dict], store_id: str) -> list[dict]:
    normalised: list[dict] = []
    for row in rows:
        ts_raw = row.get("ts") or row.get("timestamp")
        if not ts_raw:
            continue
        try:
            ts = parser.isoparse(str(ts_raw)).isoformat()
        except Exception:  # noqa: BLE001
            continue
        sid = row.get("store") or row.get("store_id") or store_id
        if store_id and sid != store_id:
            continue
        normalised.append(
            {
                "ts": ts,
                "men": _to_int(row.get("men")),
                "women": _to_int(row.get("women")),
                "total": _to_int(row.get("total")),
            }
        )
    return normalised


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
