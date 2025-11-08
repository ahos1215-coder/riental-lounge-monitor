from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

from ..config import AppConfig


def ensure_data_dir(config: AppConfig) -> None:
    config.data_dir.mkdir(parents=True, exist_ok=True)


def load_latest(config: AppConfig) -> dict[str, Any]:
    if not config.data_file.exists():
        return {}
    try:
        with config.data_file.open(encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError:
        return {}


def save_latest(config: AppConfig, record: dict[str, Any]) -> None:
    ensure_data_dir(config)
    with config.data_file.open("w", encoding="utf-8") as fh:
        json.dump(record, fh, ensure_ascii=False, indent=2)


def append_log(config: AppConfig, record: dict[str, Any]) -> None:
    ensure_data_dir(config)
    with config.log_file.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def iter_log_rows(config: AppConfig) -> Iterable[dict[str, Any]]:
    if not config.log_file.exists():
        return []
    with config.log_file.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                yield data


def rows_in_range(config: AppConfig, *, start: date, end: date) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for rec in iter_log_rows(config):
        ts = rec.get("ts")
        if not isinstance(ts, str):
            continue
        try:
            rec_date = datetime.fromisoformat(ts).date()
        except ValueError:
            continue
        if start <= rec_date <= end:
            result.append(rec)
    return result


def has_entry_for_date(config: AppConfig, day: date) -> bool:
    day_str = day.strftime("%Y-%m-%d")
    for rec in iter_log_rows(config):
        if rec.get("date") == day_str:
            return True
    return False