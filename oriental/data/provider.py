from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Iterable

import requests
from dateutil import parser
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class DataProvider:
    def get_records(self, store_id: str) -> list[dict]:
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

    def get_records(self, store_id: str) -> list[dict]:
        rows: list[dict] = []
        if self.read_url:
            try:
                resp = self.session.get(self.read_url, params={"store": store_id}, timeout=12)
                resp.raise_for_status()
                payload = resp.json()
                rows = payload.get("rows", payload) if isinstance(payload, dict) else payload
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
