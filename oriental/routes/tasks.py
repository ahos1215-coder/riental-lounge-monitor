from __future__ import annotations

import os
import re
import time
from datetime import datetime
from typing import Any, Tuple

from bs4 import BeautifulSoup
from flask import Blueprint, current_app, jsonify, request
from pydantic import ValidationError

from ..clients.gas_client import GasClient, GasClientError
from ..clients.google_places import GooglePlacesClient
from ..config import AppConfig
from ..data.second_venues_repository import SecondVenuesRepository
from ..tasks.update_second_venues import update_all_second_venues
from ..utils import storage, timeutil
from multi_collect import PREF_COORDS, STORES, collect_all_once

bp = Blueprint("tasks", __name__)


@bp.route("/tasks/collect", methods=["GET", "POST"])
def tasks_collect_single():
    """
    単一レコードを受け取り、GAS append のみを行うエンドポイント。
    - GET: クエリ store / men / women / ts
    - POST: JSON {store, men, women, ts}
    バリデーション失敗は 400 を返す。
    """
    logger = current_app.logger
    payload = request.get_json(silent=True) or {}
    if request.method == "GET":
        payload = request.args.to_dict(flat=True)

    store = str(payload.get("store", "")).strip()
    if not store:
        return _bad_request("store is required")

    try:
        men = int(payload.get("men"))
        women = int(payload.get("women"))
    except (TypeError, ValueError):
        return _bad_request("men and women must be integers")

    ts_raw = payload.get("ts")
    try:
        ts_dt = datetime.fromisoformat(str(ts_raw))
    except Exception:  # noqa: BLE001
        return _bad_request("ts must be ISO8601 with timezone")
    if ts_dt.tzinfo is None:
        return _bad_request("ts must include timezone")

    record = {
        "store": store,
        "men": men,
        "women": women,
        "total": men + women,
        "ts": ts_dt.isoformat(),
    }

    try:
        _gas_client().append_row(record)
    except Exception as exc:  # noqa: BLE001
        logger.exception("tasks.collect.append_failed")
        return jsonify({"ok": False, "error": str(exc)}), 200

    return jsonify({"ok": True}), 200


def _bad_request(message: str):
    return jsonify({"ok": False, "error": message}), 400


@bp.route("/tasks/multi_collect", methods=["GET", "POST"])
def tasks_multi_collect():
    """
    38 店舗を multi_collect.collect_all_once() で一括収集し、Supabase(public.logs) に保存するタスク。

    正常時: {"ok": true, "stores": 38, "task": "collect_all_once"}
    異常時: {"ok": false, "error": "..."}（HTTP 200 を維持）
    """
    logger = current_app.logger
    logger.info("collect_all_once.start")
    started = time.perf_counter()

    try:
        collect_all_once()
        store_count = len(STORES)
        duration = time.perf_counter() - started
        logger.info("collect_all_once.success stores=%d duration_sec=%.3f", store_count, duration)
        return jsonify({"ok": True, "task": "collect_all_once", "stores": store_count})
    except Exception as exc:  # noqa: BLE001
        duration = time.perf_counter() - started
        logger.exception("collect_all_once.failed duration_sec=%.3f", duration)
        return jsonify({"ok": False, "task": "collect_all_once", "error": str(exc)})


@bp.route("/api/tasks/collect_all_once", methods=["GET", "POST"])
def api_tasks_collect_all_once():
    """Alias: /api/tasks/collect_all_once -> /tasks/multi_collect"""
    return tasks_multi_collect()


@bp.get("/tasks/tick")
def tasks_tick():
    cfg = _config()
    current = timeutil.now(cfg.timezone)
    is_in, start_dt, end_dt = timeutil.collection_window(
        current=current,
        start_hour=cfg.window_start,
        end_hour=cfg.window_end,
        tz_name=cfg.timezone,
    )
    window_payload = {"start": start_dt.isoformat(), "end": end_dt.isoformat()}
    if not is_in:
        return jsonify({"ok": True, "skipped": True, "reason": "outside-window", "window": window_payload})

    record = _run_collection(cfg)
    return jsonify({"ok": True, "record": record, "window": window_payload})


@bp.get("/tasks/seed")
def tasks_seed():
    cfg = _config()
    today = timeutil.now(cfg.timezone).date()
    if storage.has_entry_for_date(cfg, today):
        return jsonify({"ok": True, "seeded": False})
    record = _run_collection(cfg)
    return jsonify({"ok": True, "seeded": True, "record": record})


@bp.route("/tasks/update_second_venues", methods=["GET", "POST"])
def tasks_update_second_venues():
    cfg = _config()
    logger = current_app.logger
    api_key = os.getenv("GOOGLE_PLACES_API_KEY", "")

    stores = STORES
    if not api_key:
        logger.warning("update_second_venues.skip_no_google_api_key stores=%d", len(stores))
        return jsonify({"ok": True, "updated": 0, "stores": len(stores)})

    started = time.perf_counter()
    try:
        summary = update_all_second_venues(
            stores=stores,
            google_client=GooglePlacesClient(api_key=api_key, session=_session(), logger=logger),
            repository=SecondVenuesRepository(
                base_url=cfg.supabase_url,
                api_key=cfg.supabase_service_role_key,
                session=_session(),
                logger=logger,
            ),
            logger=logger,
            pref_coords=PREF_COORDS,
        )
        duration = time.perf_counter() - started
        logger.info(
            "update_second_venues.success stores=%d total_venues=%d duration_sec=%.3f",
            summary.get("stores", 0),
            summary.get("total_venues", 0),
            duration,
        )
        return jsonify({"ok": True, "updated": summary.get("total_venues", 0), "stores": summary.get("stores", 0)})
    except Exception as exc:  # noqa: BLE001
        duration = time.perf_counter() - started
        logger.warning("update_second_venues.failed duration_sec=%.3f detail=%s", duration, exc)
        return jsonify({"ok": True, "updated": 0, "stores": len(stores)})


def _config() -> AppConfig:
    return current_app.config["APP_CONFIG"]


def _session():
    return current_app.config["HTTP_SESSION"]


def _gas_client() -> GasClient:
    return current_app.config["GAS_CLIENT"]


def _gather_collect_payload(cfg: AppConfig) -> dict[str, Any]:
    payload = request.get_json(silent=True) or {}

    for key in ("men", "women", "total"):
        if key in request.args:
            value = request.args.get(key, type=int)
            if value is not None:
                payload.setdefault(key, value)

    if "ts" not in payload:
        ts_arg = request.args.get("ts")
        if ts_arg:
            payload["ts"] = ts_arg
        else:
            form_ts = request.form.get("ts")
            if form_ts:
                payload["ts"] = form_ts

    payload.setdefault("store", cfg.store_name)
    payload.setdefault("ts", timeutil.isoformat(timeutil.now(cfg.timezone), cfg.timezone))

    if "total" not in payload:
        men = payload.get("men")
        women = payload.get("women")
        if isinstance(men, int) and isinstance(women, int):
            payload["total"] = men + women

    return payload


def _serialise_errors(errors: list[Any]) -> list[Any]:
    serialised: list[Any] = []
    for item in errors:
        if isinstance(item, dict):
            serialised.append({k: (str(v) if isinstance(v, Exception) else v) for k, v in item.items()})
        else:
            serialised.append(str(item))
    return serialised


def _run_collection(
    config: AppConfig,
    *,
    men: int | None = None,
    women: int | None = None,
    ts: datetime | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    logger = current_app.logger
    session = _session()

    ts_dt = timeutil.ensure_timezone(ts if ts is not None else timeutil.now(config.timezone), config.timezone)

    men_value = men
    women_value = women

    if men_value is None or women_value is None:
        scraped_men, scraped_women = _scrape_oriental_counts(session, config.target_url)
        men_value = men_value if men_value is not None else scraped_men
        women_value = women_value if women_value is not None else scraped_women
        source = source or config.target_url
    else:
        source = source or "manual"

    total = men_value + women_value if (men_value is not None and women_value is not None) else None

    record = {
        "date": ts_dt.strftime("%Y-%m-%d"),
        "time": ts_dt.strftime("%H:%M"),
        "store": config.store_name,
        "men": men_value,
        "women": women_value,
        "total": total,
        "ts": ts_dt.isoformat(timespec="seconds"),
        "source": source,
    }

    storage.save_latest(config, record)
    storage.append_log(config, record)

    try:
        _gas_client().append_row(record)
    except GasClientError as exc:
        logger.warning(f"collect.gas_append_failed {exc.__class__.__name__} {exc}")

    return record


def _scrape_oriental_counts(session, url: str) -> Tuple[int | None, int | None]:
    try:
        resp = session.get(url)
        resp.raise_for_status()
    except Exception:
        return None, None

    soup = BeautifulSoup(resp.text, "lxml")

    men = _extract_count(
        soup,
        [r"(\d+)\s*(?:GENTLEMEN|Men|MEN|男性)"],
        selectors=[".men-count", ".male .count", "#menCount", "#men", ".count-men"],
    )
    women = _extract_count(
        soup,
        [r"(\d+)\s*(?:LADIES|Women|WOMEN|女性)"],
        selectors=[".women-count", ".female .count", "#womenCount", "#women", ".count-women"],
    )
    return men, women


def _extract_count(soup: BeautifulSoup, patterns: list[str], selectors: list[str]) -> int | None:
    text = soup.get_text(" ", strip=True)

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return int(match.group(1))

    for selector in selectors:
        node = soup.select_one(selector)
        if not node:
            continue
        match = re.search(r"\d+", node.get_text(strip=True))
        if match:
            return int(match.group())
    return None
