from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Tuple

from bs4 import BeautifulSoup
from flask import Blueprint, current_app, jsonify, request
from pydantic import ValidationError

# ==== プロジェクト内部 ====
from ..config import AppConfig
from ..utils import storage, timeutil
from ..utils.log import format_payload

# ==== 旧 GAS 用（残すけど使わない）====
from ..clients.gas_client import GasClient, GasClientError

# ==== 新：38店舗収集 ====
from multi_collect import collect_all_once, STORES


bp = Blueprint("tasks", __name__)


# ==========================================================
# 38 店舗一括収集タスク：Render / cron-job.org の本番エンドポイント
# ==========================================================
@bp.route("/tasks/collect", methods=["GET", "POST"])
def tasks_collect_all():
    """
    38 店舗を multi_collect.collect_all_once() で一括収集し、
    Supabase(public.logs) に自動保存するタスク。

    正常時: {"ok": true, "stores": 38}
    異常時: {"ok": false, "error": "..."} （※常に HTTP 200）
    """
    logger = current_app.logger
    logger.info("collect_all_once.start")

    try:
        # 副作用：38 店舗スクレイピング → Supabase へ INSERT
        collect_all_once()

        store_count = len(STORES)
        logger.info(f"collect_all_once.success stores={store_count}")
        return jsonify({
            "ok": True,
            "task": "collect_all_once",
            "stores": store_count
        })

    except Exception as exc:
        logger.exception("collect_all_once.failed")
        return jsonify({
            "ok": False,
            "task": "collect_all_once",
            "error": str(exc)
        })


# ==========================================================
# 旧エンドポイント（後方互換）→ すべて新しい collect_all に委譲
# ==========================================================
@bp.get("/tasks/multi_collect")
def tasks_multi_collect():
    """旧 API。内部的には /tasks/collect を呼び出すだけ。"""
    return tasks_collect_all()


# ==========================================================
# 以下は “単店舗用の旧処理” → 現在は使わないが互換のため残す
# ==========================================================

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
        return jsonify({
            "ok": True,
            "skipped": True,
            "reason": "outside-window",
            "window": window_payload
        })

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


# ==========================================================
# 単店舗用の旧ロジック（互換性維持のため残す）
# ==========================================================

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
            serialised.append({
                k: (str(v) if isinstance(v, Exception) else v)
                for k, v in item.items()
            })
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

    # 旧：単店舗スクレイピング（多店舗には使わない）
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
        selectors=[".men-count", ".male .count", "#menCount", "#men", ".count-men"]
    )
    women = _extract_count(
        soup,
        [r"(\d+)\s*(?:LADIES|Women|WOMEN|女性)"],
        selectors=[".women-count", ".female .count", "#womenCount", "#women", ".count-women"]
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
