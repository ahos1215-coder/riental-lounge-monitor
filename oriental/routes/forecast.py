from __future__ import annotations

import os
import re
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
_FORECAST_CACHE_MAX_ENTRIES = int(os.getenv("FORECAST_CACHE_MAX_ENTRIES", "500"))

from ..config import AppConfig
from ..ml.forecast_service import ForecastService
from ..ml.megribi_score import megribi_score as calc_megribi_score
from ..utils.stores import SLUG_TO_ID
from ._cache import SingleFlightTTLCache
from .common import get_config as _config, get_supabase_provider, resolve_store_id

bp = Blueprint("forecast", __name__, url_prefix="/api")

# マルチストア系エンドポイントの上限。既知の全店舗数（44店舗）を下回らないようにする。
# DoS 対策は SLUG_TO_ID による既知 slug のみのフィルタリングとレート制限で担保する。
MAX_MULTI_STORES = len(SLUG_TO_ID)

# /api/forecast_snapshot の date パラメータ（夜の JST 日付）。YYYYMMDD の8桁固定。
_NIGHT_DATE_RE = re.compile(r"^\d{8}$")


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


def _storage_get(cfg: AppConfig, path: str) -> bytes | None:
    """Supabase Storage から生バイト列を取得する共通ヘルパー。

    `_fetch_live_accuracy`（/api/forecast_accuracy）と `_fetch_forecast_snapshot`
    （/api/forecast_snapshot）の両方から使う。オブジェクトが存在しない場合
    （404、または Supabase が返す 400 の "not found" 系エラー）は None を返し、
    それ以外の HTTP エラーは呼び出し側に伝播させる（呼び出し側で握りつぶす）。
    """
    import urllib.error
    import urllib.request

    supabase_url = (cfg.supabase_url or "").rstrip("/")
    key = cfg.supabase_service_role_key or ""
    bucket = cfg.forecast_model_bucket or "ml-models"
    if not supabase_url or not key:
        return None

    endpoint = f"{supabase_url}/storage/v1/object/{bucket}/{path}"
    req = urllib.request.Request(
        endpoint, headers={"apikey": key, "Authorization": f"Bearer {key}"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        if exc.code == 400:
            try:
                body = exc.read().decode("utf-8", "replace").lower()
            except Exception:  # noqa: BLE001
                body = ""
            if "not_found" in body or "not found" in body or "object not found" in body:
                return None
        raise


def _is_num(v: object) -> bool:
    """bool を除いた実数か（JSON 由来の int/float を想定）。"""
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _night_avg_by_store(snapshot: dict | None) -> dict[str, float]:
    """予測スナップショット (accuracy/snapshots/<date>.json の by_slug) から、
    店舗ごとの「その夜の予測総数の平均」を返す。これを店舗規模（＝想定夜間来客数）の
    近似値として使い、相対誤差 relative_mae = live_mae / night_avg の分母にする。

    キーは snapshot 側と同じ slug（オリエンタルは "ol_" なしの短縮 slug、相席屋は "ay_*"）。
    予測点が無い/壊れている店は結果に含めない（呼び出し側で相対誤差を付けない）。
    純関数（ネットワーク I/O 無し）なのでユニットテストしやすい。
    """
    if not isinstance(snapshot, dict):
        return {}
    by_slug = snapshot.get("by_slug")
    if not isinstance(by_slug, dict):
        return {}
    out: dict[str, float] = {}
    for slug, points in by_slug.items():
        if not isinstance(points, list):
            continue
        vals = [
            float(p.get("total_pred"))
            for p in points
            if isinstance(p, dict) and _is_num(p.get("total_pred"))
        ]
        if vals:
            out[slug] = sum(vals) / len(vals)
    return out


def _augment_relative_fields(per_store: dict, night_avg: dict[str, float]) -> None:
    """per_store の各エントリに「店舗規模で正規化した相対性能」シグナルを追加する
    （additive・in-place、既存キーは触らない）。

    - beats_baseline: live_mae < live_baseline_mae（ナイーブ基準＝先週同時刻に勝っているか）。
      規模に依存しない頑健なシグナルで、両値が揃うときのみ付与する。
    - night_avg: 想定夜間来客数（スケール正規化の分母）。スナップショットがある店のみ。
    - relative_mae: live_mae / night_avg（店舗規模で正規化した相対誤差）。night_avg があるときのみ。

    これにより精度バッジを「絶対人数」ではなく「相対性能」で判定できる（小規模店が
    小さい MAE だけで "高精度" になり、大規模店が同等以上の相対精度でも "参考値" に
    なる逆転を解消する）。
    """
    if not isinstance(per_store, dict):
        return
    for slug, entry in per_store.items():
        if not isinstance(entry, dict):
            continue
        lm = entry.get("live_mae")
        bm = entry.get("live_baseline_mae")
        if _is_num(lm) and _is_num(bm):
            entry["beats_baseline"] = bool(lm < bm)
        avg = night_avg.get(slug)
        if _is_num(avg) and avg > 0:
            entry["night_avg"] = round(float(avg), 2)
            if _is_num(lm):
                entry["relative_mae"] = round(float(lm) / float(avg), 3)


def _fetch_live_accuracy(cfg: AppConfig) -> dict | None:
    """Supabase Storage の答え合わせ結果 (scripts/score_forecasts.py が毎晩書き込む)
    から実測精度を組み立てる。summary.json が無い/壊れている、または nights が
    空なら None を返す（呼び出し側は holdout の metrics にフォールバックする）。
    Storage 障害でエンドポイント全体を落とさないよう、例外はすべてここで握りつぶす。
    """
    import json

    try:
        raw = _storage_get(cfg, "accuracy/scores/summary.json")
        if raw is None:
            return None
        summary = json.loads(raw.decode())
        nights = summary.get("nights")
        if not isinstance(nights, list) or not nights:
            return None

        def _avg(key_name: str, n: int) -> float | None:
            vals = [
                x.get(key_name) for x in nights[:n]
                if isinstance(x.get(key_name), (int, float))
            ]
            return round(sum(vals) / len(vals), 2) if vals else None

        # mae_30d は「本当に30夜以上」蓄積されるまで null にする。7夜しか無いのに
        # mae_7d と同値を「30日平均」と称するのは不誠実なラベルになるため。
        # フロントは nights_count と合わせて「n=X夜」表示にフォールバックする。
        n_nights = len(nights)
        live: dict = {
            "mae_7d": _avg("overall_live_mae", 7),
            "mae_30d": _avg("overall_live_mae", 30) if n_nights >= 30 else None,
            "baseline_7d": _avg("overall_baseline_mae", 7),
            "nights_count": n_nights,
            "updated_at": summary.get("updated_at_utc"),
            "stores_scored_latest": nights[0].get("stores_scored"),
            "per_store": {},
        }

        latest_date = nights[0].get("night_date")
        if latest_date:
            daily_raw = _storage_get(cfg, f"accuracy/scores/{latest_date}.json")
            if daily_raw is not None:
                daily = json.loads(daily_raw.decode())
                per_store = daily.get("per_store")
                if isinstance(per_store, dict):
                    live["per_store"] = per_store

        # 追加(後方互換): 店舗規模で正規化した相対性能シグナル（beats_baseline /
        # night_avg / relative_mae）を per_store に付与する。分母の「想定夜間来客数」は
        # その夜の予測スナップショットの総数平均で近似する（1 リクエスト＝Storage 1 read
        # 追加のみ）。スナップショットが無い/壊れていても beats_baseline は日次スコアだけで
        # 付き、relative_mae のみスキップされる（カードは相対誤差なしでも基準比較で判定可能）。
        if live["per_store"] and latest_date:
            night_avg: dict[str, float] = {}
            try:
                snap_raw = _storage_get(cfg, f"accuracy/snapshots/{latest_date}.json")
                if snap_raw is not None:
                    night_avg = _night_avg_by_store(json.loads(snap_raw.decode()))
            except Exception:  # noqa: BLE001 — スナップショット取得/解析失敗は相対誤差なしで続行
                night_avg = {}
            _augment_relative_fields(live["per_store"], night_avg)

        return live
    except Exception:  # noqa: BLE001
        # Storage 障害・パース失敗は「実測精度なし」として holdout にフォールバックさせる
        current_app.logger.warning("api_forecast_accuracy.live_fetch_failed", exc_info=True)
        return None


def _fetch_forecast_snapshot(cfg: AppConfig, date: str) -> dict | None:
    """その夜（JST, YYYYMMDD）に実際に配信されていた予測のスナップショットを読み込む。

    scripts/snapshot_forecasts.py が毎晩 ~18:10 JST（夜が始まる前）に
    `<bucket>/accuracy/snapshots/<date>.json` として保存したものをそのまま返す。
    ファイルが無い（まだ書き込まれていない新しい夜 / この機能導入前の古い夜）、
    または壊れている場合は None を返す（呼び出し側は ok:false として扱い、
    実測グラフのみ表示にフォールバックする＝エラーではない）。
    """
    import json

    try:
        raw = _storage_get(cfg, f"accuracy/snapshots/{date}.json")
        if raw is None:
            return None
        return json.loads(raw.decode())
    except Exception:  # noqa: BLE001
        current_app.logger.warning(
            "api_forecast_snapshot.fetch_failed date=%s", date, exc_info=True
        )
        return None


@bp.get("/forecast_accuracy")
def api_forecast_accuracy():
    """Return per-store accuracy: 学習時の holdout metrics（後方互換）に加え、
    Supabase Storage に蓄積された本番の答え合わせ結果（live）を返す。
    """
    import json
    from pathlib import Path

    cfg = _config()
    cache_dir = Path(cfg.forecast_model_cache_dir)
    metadata_path = cache_dir / "metadata.json"

    if not metadata_path.exists():
        return jsonify({"ok": False, "error": "metadata-not-found"}), 404

    try:
        meta = json.loads(metadata_path.read_text(encoding="utf-8"))
    except Exception:
        return jsonify({"ok": False, "error": "metadata-parse-error"}), 500

    metrics = meta.get("metrics")
    if not metrics:
        return jsonify({"ok": False, "error": "no-metrics-in-metadata"}), 404

    live = _fetch_live_accuracy(cfg)

    return jsonify({
        "ok": True,
        "trained_at": meta.get("trained_at"),
        "metrics": metrics,
        "live": live,
    })


@bp.get("/forecast_snapshot")
def api_forecast_snapshot():
    """完了済みの夜（昨日・先週・カスタムの過去日、または今日モードで既に夜が
    終わっている場合）に「実際にその夜配信されていた予測」を返す、答え合わせ用
    オーバーレイ。/api/forecast_today は常に "これからの夜" しか返さないため、
    終わった夜の予測を後から見るにはこのスナップショット（毎晩 ~18:10 JST に
    scripts/snapshot_forecasts.py が保存）を読むしかない。

    ?store=<slug>&date=<YYYYMMDD> （date は対象の夜の JST 開始日＝19:00 側の日付）。

    スナップショットが無い（対象の夜がまだ新しすぎる/この機能導入前で記録が無い）
    場合は ok:false・HTTP 200 を返す（エラーではなく「無いのが正常」なケース）。
    store/date が不正な場合のみ 400。
    """
    cfg = _config()

    store = (request.args.get("store") or "").strip().lower()
    date = (request.args.get("date") or "").strip()

    if store not in SLUG_TO_ID:
        return jsonify({"ok": False, "error": "invalid-store"}), 400
    if not _NIGHT_DATE_RE.match(date):
        return jsonify({"ok": False, "error": "invalid-date"}), 400

    snapshot = _fetch_forecast_snapshot(cfg, date)
    by_slug = snapshot.get("by_slug") if isinstance(snapshot, dict) else None
    data = by_slug.get(store) if isinstance(by_slug, dict) else None

    if not isinstance(data, list):
        current_app.logger.info(
            "api_forecast_snapshot.missing store=%s date=%s", store, date
        )
        resp = jsonify({"ok": False, "date": date, "data": []})
    else:
        current_app.logger.info(
            "api_forecast_snapshot.success store=%s date=%s points=%d",
            store, date, len(data),
        )
        resp = jsonify({"ok": True, "date": date, "data": data})

    # 過去の夜のスナップショットは不変（もう書き換わらない）→ 長め CDN キャッシュ。
    # ok:false（未記録）も含め、同じ date は将来も同じ結果になるため一緒に長くキャッシュしてよい。
    resp.headers["Cache-Control"] = "public, s-maxage=86400, stale-while-revalidate=604800"
    return resp
