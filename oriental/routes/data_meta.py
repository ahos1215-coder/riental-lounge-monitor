"""/api/meta, /api/holiday_status, /api/second_venues — メタ情報系ハンドラ。

data.py から機械的に分離（B8 route split）。ハンドラは `.data` の Blueprint
`bp` にそのまま生えるため、URL / エンドポイント名は一切変わらない。
"""

from __future__ import annotations

from flask import current_app, jsonify, request

from ..data.second_venues_repository import SecondVenuesRepository
from ..utils import timeutil
from ..utils.log import format_payload
from .common import get_config as _config, resolve_store_id
from .data import bp

_resolve_store_id = resolve_store_id


@bp.get("/api/meta")
def api_meta():
    cfg = _config()
    data = cfg.summary()
    data["forecast_model"] = _forecast_model_status()
    return jsonify({"ok": True, "data": data})


@bp.get("/api/holiday_status")
def api_holiday_status():
    """連休判定 API。フロントの連休バナー表示などに使う。

    Query:
        date (optional, YYYY-MM-DD): 判定対象日。省略時は JST の今日。

    Response:
        {
          "ok": true,
          "date": "2026-05-03",
          "block_length": 5,         # 連続休業ブロックの全長 (0=平日)
          "block_position": 0.25,    # ブロック内位置 (0.0=初日, 1.0=最終日)、平日のときは 0.5
          "is_long_holiday": true,   # block_length >= 4
          "label": "連休中 (2/5日目)" # 表示用ラベル
        }
    """
    from datetime import date as date_cls

    from ..ml.holiday_calendar import get_holiday_block, is_long_holiday

    raw = (request.args.get("date") or "").strip()
    if raw:
        try:
            target = date_cls.fromisoformat(raw)
        except ValueError:
            return jsonify({"ok": False, "error": "invalid date format (expected YYYY-MM-DD)"}), 400
    else:
        # JST の今日 (00:00 区切り)
        target = timeutil.now("Asia/Tokyo").date()

    block_length, block_position = get_holiday_block(target)
    long_flag = is_long_holiday(target)

    if block_length == 0:
        label = "平日"
    elif block_length == 1:
        label = "単発の祝日"
    elif block_length == 2:
        label = "通常の週末"
    else:
        # block_position が None なら 0.5、ブロック内日数 (1-indexed) を出す
        pos = block_position if block_position is not None else 0.5
        day_in_block = round(pos * (block_length - 1)) + 1
        label = f"{block_length}連休 ({day_in_block}/{block_length}日目)"

    return jsonify({
        "ok": True,
        "date": target.isoformat(),
        "block_length": block_length,
        "block_position": block_position if block_position is not None else 0.5,
        "is_long_holiday": long_flag,
        "label": label,
    })


@bp.get("/api/second_venues")
def api_second_venues():
    logger = current_app.logger
    params_dict = request.args.to_dict(flat=False)
    logger.info("api_second_venues.start params=%s", format_payload(params_dict))

    cfg = _config()
    store_id = _resolve_store_id(cfg)

    if not (cfg.supabase_url and cfg.supabase_service_role_key):
        logger.warning("api_second_venues.supabase_missing_config store_id=%s", store_id)
        # 未設定は「データなし」ではなく取得不可なので ok:false で監視・フロントに伝える
        # （rows は空のままにしておき、UI 側は空表示できる）
        return jsonify({"ok": False, "error": "supabase-not-configured", "rows": []})

    repo = SecondVenuesRepository(
        base_url=cfg.supabase_url,
        api_key=cfg.supabase_service_role_key,
        session=current_app.config.get("HTTP_SESSION"),
        logger=logger,
    )

    try:
        rows = repo.get_by_store(store_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("api_second_venues.fetch_failed store_id=%s detail=%s", store_id, exc)
        return jsonify({"ok": False, "error": str(exc), "rows": []})

    return jsonify({"ok": True, "rows": rows})


def _forecast_model_status() -> dict:
    service = current_app.config.get("FORECAST_SERVICE")
    if service is None or getattr(service, "model_registry", None) is None:
        return {
            "loaded": False,
            "schema_version": None,
            "trained_at": None,
            "loaded_at_unix": None,
            "age_sec": None,
            "note": "forecast_service_not_initialized",
        }
    return service.model_registry.current_status()
