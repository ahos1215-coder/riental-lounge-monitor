from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Blueprint, current_app, jsonify, request

# Flask プロセス内でのキャッシュ TTL（秒）
# ワーカーごとに独立するが、CDN キャッシュと合わせて十分な効果がある。
# 実測データは5分おきにしか更新されないため、60秒は過剰に短く不要な再計算を招いていた
# → 180秒に緩和（2026-07）。キャッシュキー/失効ロジックは変更なし。
_FORECAST_CACHE_TTL = int(os.getenv("FORECAST_RESULT_CACHE_TTL", "180"))  # 3 分

# 同じキーへの同時アクセスが cold なとき、合流待ちを諦めるまでの秒数。
# gunicorn のスレッド数(4)を大きく超えて待たせないための保険（fail-open）。
_FORECAST_CACHE_WAIT_TIMEOUT = float(os.getenv("FORECAST_CACHE_WAIT_TIMEOUT", "25"))
# 既定 120。warm な forecast キー母集団（全42店の today/next_hour + multi ≒ 70）を
# 収容しつつ絞る。forecast エントリは実測 ~16KB/件と軽く 120 件でも ~2MB/worker と
# 小さいが、上限 500 のまま放置する理由もないため range と揃えて右サイズ化する
# （memory-budget 修正。旧既定 500）。
_FORECAST_CACHE_MAX_ENTRIES = int(os.getenv("FORECAST_CACHE_MAX_ENTRIES", "120"))

from ..ml.forecast_service import ForecastService
from ..ml.megribi_score import megribi_score as calc_megribi_score
from ..utils.stores import SLUG_TO_ID
from ._cache import SingleFlightTTLCache
from .common import get_config as _config, get_supabase_provider, resolve_store_id

bp = Blueprint("forecast", __name__, url_prefix="/api")

# マルチストア系エンドポイントの上限。既知の全店舗数（42店舗）を下回らないようにする。
# DoS 対策は SLUG_TO_ID による既知 slug のみのフィルタリングとレート制限で担保する。
MAX_MULTI_STORES = len(SLUG_TO_ID)


def _service() -> ForecastService:
    if "FORECAST_SERVICE" not in current_app.config:
        current_app.config["FORECAST_SERVICE"] = ForecastService.from_app(current_app)
    return current_app.config["FORECAST_SERVICE"]


def _guard():
    if not _config().enable_forecast:
        return jsonify({"ok": False, "error": "forecast-disabled"}), 503
    return None


def _error_status(raw: dict) -> int:
    err = raw.get("error")
    if err in {"model_schema_mismatch", "model_unavailable"}:
        return 503
    # 予期せぬ内部エラーは 5xx にして監視・フロントが「予測利用不可」を検知できるようにする
    if err == "forecast_internal_error":
        return 500
    return 200


# ---------- in-process TTL キャッシュ + single-flight 合流 ----------
#
# キャッシュに入れる値は常に (body, http_status) のタプル。body はそのまま
# jsonify() できる dict、http_status は成功時 200 / エラー時 5xx。エンベロープ
# を統一しているのは、/api/forecast_today（単体）と /api/forecast_today_multi
# （店舗別の内部 fetch）が同じキャッシュキー("today:<store_id>")を共有し、
# どちらが先に計算してもキャッシュの形が一致するようにするため
# （forecast_today_multi._fetch_one 側を参照）。

def _forecast_cache() -> SingleFlightTTLCache:
    if "FORECAST_RESULT_CACHE" not in current_app.config:
        current_app.config["FORECAST_RESULT_CACHE"] = SingleFlightTTLCache(
            ttl=_FORECAST_CACHE_TTL,
            max_entries=_FORECAST_CACHE_MAX_ENTRIES,
            wait_timeout=_FORECAST_CACHE_WAIT_TIMEOUT,
        )
    return current_app.config["FORECAST_RESULT_CACHE"]


_supabase_provider = get_supabase_provider
_resolve_store_id = resolve_store_id


def _normalize_points(result: dict, logger=None) -> list[dict]:
    """
    どんな結果が来ても、
    - data は「配列 list」
    - 各要素は ts を持つ dict
    という形にそろえる。

    `logger` を明示的に受け取れるようにしているのは、ThreadPoolExecutor の
    ワーカースレッド（forecast_today_multi._fetch_one など、Flask のリクエスト
    コンテキストを持たない）から呼ばれても current_app プロキシに触れずに
    安全にログを出せるようにするため。省略時は current_app.logger を使う
    （単体エンドポイントは自スレッド=リクエストスレッドなので安全）。
    """
    log = logger if logger is not None else current_app.logger

    if not isinstance(result, dict):
        log.warning("api_forecast.result_not_dict -> normalize_to_empty_list")
        return []

    data = result.get("data")

    if isinstance(data, list):
        filtered = [d for d in data if isinstance(d, dict) and "ts" in d]
        if len(filtered) != len(data):
            log.warning(
                "api_forecast.data_list_had_invalid_entries -> filtered=%d -> %d",
                len(data),
                len(filtered),
            )
        return filtered

    # data が {} や None, 数値など → 空配列にする
    log.warning(
        "api_forecast.data_not_list -> normalize_to_empty_list type=%s",
        type(data),
    )
    return []


@bp.get("/forecast_next_hour")
def forecast_next_hour():
    guard = _guard()
    if guard:
        return guard

    cfg = _config()
    store = _resolve_store_id(cfg)
    freq = max(1, int(os.getenv("FORECAST_FREQ_MIN", "15")))
    logger = current_app.logger

    cache_key = f"next_hour:{store}"

    def _compute() -> tuple[tuple[dict, int], bool]:
        logger.info("api_forecast.start store=%s horizon=next_hour", store)
        raw = _service().forecast_next_hour(store_id=store, freq_min=freq)
        if not raw.get("ok", True):
            logger.warning("api_forecast.error store=%s detail=%s", store, raw.get("detail"))
            return (raw, _error_status(raw)), False
        points = _normalize_points(raw, logger)
        logger.info("api_forecast.success store=%s points=%d", store, len(points))

        result = {
            "ok": True,
            "data": points,
            "reasoning": raw.get("reasoning", {}),
            "insufficient_history": bool(raw.get("insufficient_history", False)),
            # closed-loop 後処理（ベースライン・ブレンド/深夜帯クランプ）が実際に効いたかを
            # 観測できるよう、service の raw 結果からそのまま透過する（後方互換の追加のみ）。
            "blend_w_ml": raw.get("blend_w_ml"),
            "blended_slots": raw.get("blended_slots"),
            "clamped_slots": raw.get("clamped_slots"),
        }
        return (result, 200), True

    (body, http_status), cache_status = _forecast_cache().get_or_compute(cache_key, _compute)
    logger.info(
        "api_forecast.request store=%s horizon=next_hour cache=%s", store, cache_status
    )
    if http_status != 200:
        return jsonify(body), http_status
    return jsonify(body)


@bp.get("/forecast_today")
def forecast_today():
    guard = _guard()
    if guard:
        return guard

    cfg = _config()
    store = _resolve_store_id(cfg)
    freq = max(1, int(os.getenv("FORECAST_FREQ_MIN", "15")))
    logger = current_app.logger

    start_h = int(os.getenv("NIGHT_START_H", "19"))
    end_h = int(os.getenv("NIGHT_END_H", "5"))

    cache_key = f"today:{store}"

    def _compute() -> tuple[tuple[dict, int], bool]:
        logger.info("api_forecast.start store=%s horizon=today", store)
        raw = _service().forecast_today(
            store_id=store, freq_min=freq, start_h=start_h, end_h=end_h
        )
        if not raw.get("ok", True):
            logger.warning("api_forecast.error store=%s detail=%s", store, raw.get("detail"))
            return (raw, _error_status(raw)), False
        points = _normalize_points(raw, logger)
        logger.info("api_forecast.success store=%s points=%d", store, len(points))

        result = {
            "ok": True,
            "data": points,
            "reasoning": raw.get("reasoning", {}),
            "insufficient_history": bool(raw.get("insufficient_history", False)),
            # closed-loop 後処理（ベースライン・ブレンド/深夜帯クランプ）が実際に効いたかを
            # 観測できるよう、service の raw 結果からそのまま透過する（後方互換の追加のみ）。
            "blend_w_ml": raw.get("blend_w_ml"),
            "blended_slots": raw.get("blended_slots"),
            "clamped_slots": raw.get("clamped_slots"),
        }
        return (result, 200), True

    # このキャッシュキーは forecast_today_multi._fetch_one とも共有される
    # （同じ店舗の today 予測をどちらが先に計算しても合流できるようにするため）。
    (body, http_status), cache_status = _forecast_cache().get_or_compute(cache_key, _compute)
    logger.info(
        "api_forecast.request store=%s horizon=today cache=%s", store, cache_status
    )
    if http_status != 200:
        return jsonify(body), http_status
    return jsonify(body)


@bp.get("/forecast_today_multi")
def forecast_today_multi():
    """複数店舗の forecast_today を1リクエストで返す。
    ?stores=slug1,slug2,... で最大 MAX_MULTI_STORES 店舗（既知の全店舗数）。
    ThreadPoolExecutor で並列実行 — 12店舗でも ~1-2s。
    """
    guard = _guard()
    if guard:
        return guard

    cfg = _config()
    logger = current_app.logger

    raw_stores = request.args.get("stores") or ""
    slugs = [s.strip().lower() for s in raw_stores.split(",") if s.strip()]
    valid = [(s, SLUG_TO_ID[s]) for s in slugs if s in SLUG_TO_ID][:MAX_MULTI_STORES]

    if not valid:
        return jsonify({"ok": False, "error": "no-valid-stores"}), 422

    freq = max(1, int(os.getenv("FORECAST_FREQ_MIN", "15")))
    start_h = int(os.getenv("NIGHT_START_H", "19"))
    end_h = int(os.getenv("NIGHT_END_H", "5"))

    # Flask コンテキスト外のスレッドで使えるよう、参照を先に取得
    # （current_app プロキシはワーカースレッドの中では使えないため、
    # service/cache/logger は必ずここで実体を取り出しておく）。
    service = _service()
    cache = _forecast_cache()

    def _fetch_one(slug: str, store_id: str):
        # forecast_today（単体エンドポイント）と全く同じキー・エンベロープ
        # ("today:<store_id>" -> (body_dict, http_status)) を使うことで、
        # 店舗ページのサーバー側/クライアント側リクエストとこの multi 経路の
        # どちらが先に来ても single-flight で合流し、ML 推論を1回にできる。
        cache_key = f"today:{store_id}"

        def _compute() -> tuple[tuple[dict, int], bool]:
            raw = service.forecast_today(
                store_id=store_id, freq_min=freq, start_h=start_h, end_h=end_h
            )
            if not raw.get("ok", True):
                body = {"ok": False, "data": [], "error": raw.get("error") or "forecast_failed"}
                return (body, _error_status(raw)), False

            points = _normalize_points(raw, logger)
            result = {
                "ok": True,
                "data": points,
                # forecast_today と同様、後処理の効き具合を店舗別に観測できるよう透過する。
                "blend_w_ml": raw.get("blend_w_ml"),
                "blended_slots": raw.get("blended_slots"),
                "clamped_slots": raw.get("clamped_slots"),
            }
            return (result, 200), True

        (body, _http_status), cache_status = cache.get_or_compute(cache_key, _compute)
        return slug, body, cache_status

    by_slug: dict = {}
    errors_by_slug: dict = {}
    cache_counts: dict[str, int] = {}
    with ThreadPoolExecutor(max_workers=min(12, len(valid))) as pool:
        futures = {pool.submit(_fetch_one, s, sid): s for s, sid in valid}
        for fut in as_completed(futures):
            try:
                slug_key, data, cache_status = fut.result()
                by_slug[slug_key] = data
                cache_counts[cache_status] = cache_counts.get(cache_status, 0) + 1
            except Exception as exc:
                slug_key = futures[fut]
                by_slug[slug_key] = {"ok": False, "data": [], "error": str(exc)}
                cache_counts["error"] = cache_counts.get("error", 0) + 1

    # 個別店舗の失敗を可視化する（全体は ok:true / 200 のまま、追加フィールドのみ）
    for slug_key, entry in by_slug.items():
        if isinstance(entry, dict) and not entry.get("ok", True):
            errors_by_slug[slug_key] = entry.get("error") or "unknown_error"

    logger.info(
        "api_forecast_today_multi.success count=%d partial_failure_count=%d cache=%s",
        len(by_slug),
        len(errors_by_slug),
        cache_counts,
    )
    return jsonify({
        "ok": True,
        "by_slug": by_slug,
        "partial_failure_count": len(errors_by_slug),
        "errors_by_slug": errors_by_slug,
    })


@bp.get("/megribi_score")
def api_megribi_score():
    """各店舗の最新データから megribi_score を計算して返す。
    ?store=slug または ?stores=slug1,slug2 で対象指定。
    省略時は全店舗を返す。
    """
    from ..utils.stores import AISEKIYA_TOTAL_CAPACITY, SLUG_TO_ID

    cfg = _config()
    logger = current_app.logger

    single = request.args.get("store")
    multi = request.args.get("stores")

    if single:
        slugs = [single.strip().lower()]
    elif multi:
        slugs = [s.strip().lower() for s in multi.split(",") if s.strip()]
    else:
        slugs = list(SLUG_TO_ID.keys())

    backend = (cfg.data_backend or "legacy").lower()
    if backend != "supabase" or not (cfg.supabase_url and cfg.supabase_service_role_key):
        return jsonify({"ok": False, "error": "supabase-required"}), 501

    provider = _supabase_provider(cfg)
    if provider is None:
        return jsonify({"ok": False, "error": "supabase-unavailable"}), 502

    valid_slugs = [(s, SLUG_TO_ID[s]) for s in slugs[:MAX_MULTI_STORES] if s in SLUG_TO_ID]

    def _fetch_one(slug: str, store_id: str):
        rows = provider.fetch_range(store_id=store_id, limit=1)
        if not rows:
            return None
        latest = rows[-1]
        total = float(latest.get("total", 0) or 0)
        men = float(latest.get("men", 0) or 0)
        women = float(latest.get("women", 0) or 0)
        is_aisekiya = store_id.startswith("ay_")
        if is_aisekiya:
            capacity = float(AISEKIYA_TOTAL_CAPACITY.get(store_id, 80.0))
        else:
            capacity = 80.0
        occupancy_rate = min(total / capacity, 1.0) if capacity > 0 else 0.0
        female_ratio = women / total if total > 0 else 0.5
        score = calc_megribi_score(
            female_ratio=female_ratio,
            occupancy_rate=occupancy_rate,
        )

        item = {
            "slug": slug,
            "score": round(score, 3),
            "total": int(total),
            "men": int(men),
            "women": int(women),
            "female_ratio": round(female_ratio, 3),
            "occupancy_rate": round(occupancy_rate, 3),
            "ts": latest.get("ts", ""),
            "men_seat_pct": None,
            "women_seat_pct": None,
        }
        if is_aisekiya:
            # 相席屋 (ay_*) は %表示のみが正式仕様。生の推定人数はフロントに渡さず、
            # 席の埋まり具合(%)をサーバー側で計算して渡す
            # （home-client.tsx の seatFullnessPercent(count, perGenderCapacity) と同じ換算）。
            per_gender_capacity = capacity / 2 if capacity > 0 else 0.0
            if per_gender_capacity > 0:
                item["men_seat_pct"] = round(min(1.0, men / per_gender_capacity) * 100)
                item["women_seat_pct"] = round(min(1.0, women / per_gender_capacity) * 100)
            item["men"] = None
            item["women"] = None
            item["total"] = None
        return item

    results = []
    with ThreadPoolExecutor(max_workers=min(12, len(valid_slugs) or 1)) as pool:
        futures = {pool.submit(_fetch_one, s, sid): s for s, sid in valid_slugs}
        for fut in as_completed(futures):
            try:
                item = fut.result()
                if item:
                    results.append(item)
            except Exception:
                pass

    results.sort(key=lambda r: r["score"], reverse=True)
    logger.info("api_megribi_score.success count=%d", len(results))
    return jsonify({"ok": True, "data": results})


# 分割先モジュールを import して、そのハンドラを上の `bp` に登録する（副作用 import）。
# forecast_accuracy は `from .forecast import bp` で同じ Blueprint を掴むため、
# ここで import しておかないと register_blueprint の時点で forecast_accuracy /
# forecast_snapshot が url_map から欠落する。
from . import forecast_accuracy  # noqa: E402,F401
