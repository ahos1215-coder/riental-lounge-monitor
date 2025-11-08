from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from requests import Response

from .http import ConfiguredSession


class GasClientError(RuntimeError):
    pass


@dataclass(slots=True)
class GasClient:
    session: ConfiguredSession
    webhook_url: str
    read_url: str

    def append_row(self, payload: dict[str, Any]) -> None:
        if not self.webhook_url:
            return
        resp = self.session.post(self.webhook_url, json=payload)
        _raise_for_status(resp, "append_row")

    def fetch_range(self, *, start: date, end: date) -> list[dict[str, Any]]:
        if not self.read_url:
            return []
        resp = self.session.get(
            self.read_url,
            params={"from": start.strftime("%Y-%m-%d"), "to": end.strftime("%Y-%m-%d")},
        )
        _raise_for_status(resp, "fetch_range")
        try:
            body = resp.json()
        except ValueError as exc:  # pragma: no cover - defensive
            raise GasClientError("invalid JSON from GAS") from exc
        rows = body.get("rows", []) if isinstance(body, dict) else []
        normalised: list[dict[str, Any]] = []
        for rec in rows:
            if not isinstance(rec, dict):
                continue
            normalised.append({
                **rec,
                "men": _to_int(rec.get("men")),
                "women": _to_int(rec.get("women")),
                "total": _to_int(rec.get("total")),
            })
        return normalised


def _raise_for_status(resp: Response, action: str) -> None:
    if resp.ok:
        return
    raise GasClientError(f"{action} failed with status {resp.status_code}")


def _to_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None