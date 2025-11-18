from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Tuple

from bs4 import BeautifulSoup
from flask import Blueprint, current_app, jsonify, request
from pydantic import ValidationError

from ..clients.gas_client import GasClient, GasClientError
from ..config import AppConfig
from ..schemas.payloads import CollectIn
from ..utils import storage, timeutil
from ..utils.log import format_payload
from multi_collect import collect_all_once


bp = Blueprint("tasks", __name__)


@bp.route("/tasks/collect", methods=["GET", "POST"])
def collect_task():
    cfg = _config()
    logger = current_app.logger
    payload_data = _gather_collect_payload(cfg)
    logger.info("collect.start payload=%s", format_payload(payload_data))
    try:
        payload = CollectIn.model_validate(payload_data)
    except ValidationError as exc:
        error_items = _serialise_errors(exc.errors())
        logger.warning("collect.validation_error errors=%s", format_payload(error_items))
        return jsonify({"ok": False, "errors": error_items}), 400

    try:
        record = _run_collection(
            cfg,
            men=payload.men,
            women=payload.women,
            ts=payload.ts,
            source=payload_data.get("source"),
        )
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error("collect.error type=%s detail=%s", exc.__class__.__name__, exc)
        raise

    logger.info(
        "collect.success store=%s ts=%s men=%s women=%s total=%s source=%s",
        record.get("store"),
        record.get("ts"),
        record.get("men"),
        record.get("women"),
        record.get("total"),
        record.get("source"),
    )
    return jsonify({"ok": True, "record": record})


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
            converted = {}
            for key, value in item.items():
                if isinstance(value, dict):
                    converted[key] = {
                        sub_key: (str(sub_val) if isinstance(sub_val, Exception) else sub_val)
                        for sub_key, sub_val in value.items()
                    }
                elif isinstance(value, Exception):
                    converted[key] = str(value)
                else:
                    converted[key] = value
            serialised.append(converted)
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
        logger.warning("collect.gas_append_failed type=%s detail=%s", exc.__class__.__name__, exc)

    return record


def _scrape_oriental_counts(session, url: str) -> Tuple[int | None, int | None]:
    logger = current_app.logger
    try:
        resp = session.get(url)
        resp.raise_for_status()
    except Exception as exc:  # pragma: no cover - network failure
        logger.error("collect.scrape_error type=%s detail=%s", exc.__class__.__name__, exc)
        return None, None

    soup = BeautifulSoup(resp.text, "lxml")
    men = _extract_count(soup, [
        r"(\d+)\s*(?:GENTLEMEN|Men|MEN|男性)",
        r"(?:GENTLEMEN|Men|MEN|男性)[^\d]{0,10}(\d+)",
    ], selectors=[
        ".men-count", ".male .count", "#menCount", "#men", ".count-men",
        '[data-role="men"]', '[data-gender="male"]',
    ])
    women = _extract_count(soup, [
        r"(\d+)\s*(?:LADIES|Women|WOMEN|女性)",
        r"(?:LADIES|Women|WOMEN|女性)[^\d]{0,10}(\d+)",
    ], selectors=[
        ".women-count", ".female .count", "#womenCount", "#women", ".count-women",
        '[data-role="women"]', '[data-gender="female"]',
    ])
    return men, women


def _extract_count(soup: BeautifulSoup, patterns: list[str], selectors: list[str]) -> int | None:
    text = soup.get_text(" ", strip=True)
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return int(match.group(1))

    for selector in selectors:
        node = soup.select_one(selector)
        if not node:
            continue
        match = re.search(r"\d+", node.get_text(strip=True).replace(",", ""))
        if match:
            return int(match.group())
    return None
# ======== ここから新規追加: /tasks/multi_collect ========

@bp.get("/tasks/multi_collect")
def tasks_multi_collect():
    """
    全店舗の人数を multi_collect.collect_all_once() で一括スクレイピングして
    GAS(doPost) に送るタスク。
    - multi_collect.py の正常動作が前提。
    - 本関数は「成功したか / 何件処理したか」だけを返す簡易API。
    """

    logger = current_app.logger

    try:
        # multi_collect.py 側で全店舗処理して GAS へ送信
        results = collect_all_once()   # ← ここが全てをやってくれる
    except Exception as exc:
        logger.error(
            "multi_collect.error type=%s detail=%s",
            exc.__class__.__name__,
            exc
        )
        return jsonify({"ok": False, "error": str(exc)}), 500

    # 正常終了
    return jsonify({
        "ok": True,
        "count": len(results),   # 実際に処理した店舗数（38 になる想定）
        "results": results
    })
