from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from flask import Blueprint, Response, current_app, jsonify, render_template, request

from ..clients.gas_client import GasClientError
from ..config import AppConfig
from ..utils import storage, timeutil
from ..utils.log import format_payload

bp = Blueprint("data", __name__)


@dataclass(slots=True)
class RangeQuery:
    start: date
    end: date
    limit: int


class RangeQueryError(ValueError):
    pass


def _config() -> AppConfig:
    return current_app.config["APP_CONFIG"]


@bp.get("/")
def index() -> str | Response:
    try:
        return render_template("index.html")
    except Exception:  # pragma: no cover
        cfg = _config()
        return jsonify({"msg": "index.html missing", "current": storage.load_latest(cfg)})


@bp.get("/api/current")
def api_current():
    cfg = _config()
    return jsonify(storage.load_latest(cfg))


@bp.get("/api/range")
def api_range():
    cfg = _config()
    logger = current_app.logger
    params_dict = request.args.to_dict(flat=False)
    logger.info("api_range.start params=%s", format_payload(params_dict))

    try:
        query = _parse_range_query(cfg)
    except RangeQueryError as exc:
        logger.warning(
            "api_range.validation_error detail=%s params=%s",
            exc,
            format_payload(params_dict),
        )
        return jsonify({"ok": False, "error": "invalid-parameters", "detail": str(exc)}), 422

    rows = list(storage.rows_in_range(cfg, start=query.start, end=query.end))
    local_count = len(rows)

    gas_client = current_app.config["GAS_CLIENT"]
    remote_count = 0
    try:
        remote_rows = gas_client.fetch_range(start=query.start, end=query.end)
        remote_count = len(remote_rows)
        rows.extend(remote_rows)
    except GasClientError as exc:
        logger.error(
            "api_range.upstream_error type=%s detail=%s window=%s..%s",
            exc.__class__.__name__,
            exc,
            query.start,
            query.end,
        )
        return jsonify({"ok": False, "error": "upstream-google-sheets", "detail": str(exc)}), 502

    deduped = _deduplicate_by_ts(rows)
    limited = deduped[-query.limit:]

    logger.info(
        "api_range.success window=%s..%s local=%d remote=%d returned=%d limit=%d",
        query.start,
        query.end,
        local_count,
        remote_count,
        len(limited),
        query.limit,
    )
    return jsonify({"ok": True, "rows": limited})


@bp.get("/api/meta")
def api_meta():
    return jsonify({"ok": True, "data": {}})


@bp.get("/api/heatmap")
def api_heatmap():
    return jsonify({"ok": True, "data": []})


@bp.get("/api/stores/list")
def api_stores_list():
    return jsonify({"ok": True, "data": []})


# ★★ forecast_today は完全削除しました ★★


@bp.get("/api/range_prevweek")
def api_range_prevweek():
    return jsonify({"ok": True, "data": []})


@bp.get("/api/summary")
def api_summary():
    return jsonify({"ok": True, "data": {}})


def _parse_range_query(cfg: AppConfig) -> RangeQuery:
    today = timeutil.now(cfg.timezone).date()

    raw_from = request.args.get("from")
    raw_to = request.args.get("to")
    raw_limit = request.args.get("limit")

    if raw_from:
        start = timeutil.parse_ymd(raw_from)
        if start is None:
            raise RangeQueryError("from must be a valid YYYY-MM-DD")
    else:
        start = today

    if raw_to:
        end = timeutil.parse_ymd(raw_to)
        if end is None:
            raise RangeQueryError("to must be a valid YYYY-MM-DD")
    elif raw_from:
        end = start
    else:
        end = today

    if start > end:
        raise RangeQueryError("from must be before to")

    default_limit = min(500, cfg.max_range_limit)

    if raw_limit is None or not str(raw_limit).strip():
        limit = default_limit
    else:
        try:
            limit = int(str(raw_limit).strip())
        except (TypeError, ValueError):
            raise RangeQueryError("limit must be an integer")

    limit = max(1, min(limit, cfg.max_range_limit))
    return RangeQuery(start=start, end=end, limit=limit)


def _deduplicate_by_ts(rows: list[dict]) -> list[dict]:
    seen: set[str] = set()
    uniq: list[dict] = []

    for rec in sorted(rows, key=lambda r: r.get("ts", "")):
        ts = rec.get("ts")
        if not isinstance(ts, str) or not ts:
            continue
        if ts in seen:
            continue
        seen.add(ts)
        uniq.append(rec)

    return uniq
