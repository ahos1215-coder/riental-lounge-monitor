"""/api/current, /api/range, /api/range_multi — 時系列データ取得系ハンドラ。

data.py から機械的に分離（B8 route split）。ハンドラは `.data` の Blueprint
`bp` にそのまま生えるため、URL / エンドポイント名は一切変わらない。
range 系の in-process TTL キャッシュ + single-flight 合流のグルーもここに集約する。
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, time, timezone

from flask import current_app, jsonify, request

from ..clients.gas_client import GasClientError
from ..config import AppConfig
from ..data.provider import SupabaseError, SupabaseLogsProvider
from ..utils import storage, timeutil
from ..utils.log import format_payload
from ..utils.stores import SLUG_TO_ID
from ._cache import SingleFlightTTLCache
from .common import get_config as _config, get_supabase_provider, resolve_store_id
from .data import bp

_supabase_provider = get_supabase_provider
_resolve_store_id = resolve_store_id

# マルチストア系エンドポイントの上限。既知の全店舗数（43店舗）を下回らないようにする。
# DoS 対策は SLUG_TO_ID による既知 slug のみのフィルタリングとレート制限で担保する。
MAX_MULTI_STORES = len(SLUG_TO_ID)

# /api/range, /api/range_multi の in-process キャッシュ TTL（秒）。
# 実測データは5分おきにしか更新されないため、120秒は鮮度と負荷軽減のバランスが良い
# （forecast.py の FORECAST_RESULT_CACHE_TTL=180 と同じ考え方、2026-07 の perf 監査）。
_RANGE_CACHE_TTL = int(os.getenv("RANGE_CACHE_TTL", "120"))
# 同じキーへの同時アクセスが cold なとき、合流待ちを諦めるまでの秒数（fail-open）。
_RANGE_CACHE_WAIT_TIMEOUT = float(os.getenv("RANGE_CACHE_WAIT_TIMEOUT", "25"))
# 既定 160。warm な range キー母集団（全42店×2の今夜/昨夜=84 + 関連店の43組合せ +
# 一覧/フィルタの multi ~26 ≒ 155）を丸ごと収容しつつ、上限が高すぎると 1200 行級の
# 重いボディ（実測 ~427KB/件）が積み上がって Render Starter 512MB を食い潰すため
# 絞る（旧既定 500 は per-worker 最悪 ~208MB＝OOM の主因）。詳細は fix/memory-budget。
_RANGE_CACHE_MAX_ENTRIES = int(os.getenv("RANGE_CACHE_MAX_ENTRIES", "160"))


@dataclass(slots=True)
class RangeQuery:
    start: date | None
    end: date | None
    limit: int


class RangeQueryError(ValueError):
    pass


# ---------- in-process TTL キャッシュ + single-flight 合流 ----------
#
# forecast.py の FORECAST_RESULT_CACHE と同じ仕組み（詳細は ._cache 参照）。
# キーは店舗単位（store_id + from/to + limit）で正規化する。/api/range（単体）
# と /api/range_multi（店舗別の内部 fetch）が同じキー形式を使うことで、店舗
# ページのサーバー側/クライアント側リクエストがどちらから来ても single-flight
# で合流し、Supabase への同時重複クエリを1回にできる。
#
# キャッシュに入れる値は常に (body, http_status) のタプル（forecast.py と同じ
# エンベロープ）。成功時のみ cacheable=True にし、上流エラーは TTL に乗せず
# 次のリクエストで再試行できるようにする。

def _range_cache() -> SingleFlightTTLCache:
    if "RANGE_RESULT_CACHE" not in current_app.config:
        current_app.config["RANGE_RESULT_CACHE"] = SingleFlightTTLCache(
            ttl=_RANGE_CACHE_TTL,
            max_entries=_RANGE_CACHE_MAX_ENTRIES,
            wait_timeout=_RANGE_CACHE_WAIT_TIMEOUT,
        )
    return current_app.config["RANGE_RESULT_CACHE"]


def _range_cache_key(store_id: str, start: date | None, end: date | None, limit: int) -> str:
    return f"{store_id}|{start.isoformat() if start else ''}|{end.isoformat() if end else ''}|{limit}"


@bp.get("/api/current")
def api_current():
    cfg = _config()
    return jsonify(storage.load_latest(cfg))


def _compute_range_for_store(
    *,
    cfg: AppConfig,
    logger,
    backend: str,
    store_id: str,
    query: "RangeQuery",
    provider: SupabaseLogsProvider | None,
    gas_client,
) -> tuple[tuple[dict, int], bool]:
    """1店舗ぶんの /api/range 本体を計算する。

    single-flight の leader（cold なキーを最初に引いたリクエスト）、または
    合流待ちがタイムアウトしたフォロワーが呼ぶ（`_cache.SingleFlightTTLCache`
    参照）。current_app には一切触れない（呼び出し側が cfg/logger/provider/gas_client を
    先に取り出して渡す）ため、ThreadPoolExecutor のワーカースレッド
    （api_range_multi._fetch_slug）からも安全に呼べる。

    戻り値は (body, http_status), cacheable。body はそのまま jsonify() できる
    dict、cacheable は成功時のみ True（上流エラーは TTL に乗せず、次のリクエスト
    で再試行できるようにする）。
    """
    if backend == "supabase" and provider is not None:
        if query.start and query.end:
            start_utc, end_utc = _range_bounds_to_utc(query.start, query.end, cfg.timezone)
        else:
            start_utc, end_utc = None, None
        try:
            supabase_rows = provider.fetch_range(
                store_id=store_id,
                start_ts=start_utc,
                end_ts=end_utc,
                limit=query.limit,
            )
        except SupabaseError as exc:
            logger.error(
                "api_range.supabase_error detail=%s store_id=%s window=%s..%s",
                exc,
                store_id,
                query.start,
                query.end,
            )
            body = {"ok": False, "error": "upstream-supabase", "detail": str(exc)}
            return (body, 502), False

        deduped = _deduplicate_by_ts(supabase_rows)
        limited = deduped[-query.limit:]
        logger.info(
            "api_range.success backend=supabase store_id=%s window=%s..%s returned=%d limit=%d",
            store_id,
            query.start,
            query.end,
            len(limited),
            query.limit,
        )
        body = {"ok": True, "rows": _trim_range_rows(limited)}
        return (body, 200), True

    if backend == "supabase" and provider is None:
        logger.warning(
            "api_range.supabase_missing_config fallback=legacy store_id=%s window=%s..%s",
            store_id,
            query.start,
            query.end,
        )

    # legacy フォールバック（backend != supabase、または supabase 未設定）
    if query.start and query.end:
        rows = list(storage.rows_in_range(cfg, start=query.start, end=query.end))
    else:
        rows = list(storage.iter_log_rows(cfg))
    local_count = len(rows)

    remote_count = 0
    if query.start and query.end:
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
            body = {"ok": False, "error": "upstream-google-sheets", "detail": str(exc)}
            return (body, 502), False

    deduped = _deduplicate_by_ts(rows)
    limited = deduped[-query.limit:]

    logger.info(
        "api_range.success backend=legacy window=%s..%s local=%d remote=%d returned=%d limit=%d",
        query.start,
        query.end,
        local_count,
        remote_count,
        len(limited),
        query.limit,
    )
    body = {"ok": True, "rows": _trim_range_rows(limited)}
    return (body, 200), True


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

    backend = (cfg.data_backend or "legacy").lower()
    store_id = _resolve_store_id(cfg)
    provider = _supabase_provider(cfg) if backend == "supabase" else None
    gas_client = current_app.config["GAS_CLIENT"]

    # このキャッシュキーは api_range_multi._fetch_slug とも共有される
    # （同じ店舗の range をどちらが先に計算しても single-flight で合流できる
    # ようにするため）。
    cache_key = _range_cache_key(store_id, query.start, query.end, query.limit)

    def _compute() -> tuple[tuple[dict, int], bool]:
        return _compute_range_for_store(
            cfg=cfg,
            logger=logger,
            backend=backend,
            store_id=store_id,
            query=query,
            provider=provider,
            gas_client=gas_client,
        )

    (body, http_status), cache_status = _range_cache().get_or_compute(cache_key, _compute)
    logger.info("api_range.request store_id=%s cache=%s", store_id, cache_status)
    if http_status != 200:
        return jsonify(body), http_status
    return jsonify(body)


def _parse_multi_store_slugs(raw: str, *, max_stores: int) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for part in raw.split(","):
        tok = part.strip().lower()
        if not tok or tok not in SLUG_TO_ID:
            continue
        if tok in seen:
            continue
        seen.add(tok)
        out.append(tok)
        if len(out) >= max_stores:
            break
    return out


@bp.get("/api/range_multi")
def api_range_multi():
    """複数店舗の range を1リクエストで返す（Supabase backend のみ）。"""
    cfg = _config()
    logger = current_app.logger
    params_dict = request.args.to_dict(flat=False)
    logger.info("api_range_multi.start params=%s", format_payload(params_dict))

    try:
        query = _parse_range_query(cfg)
    except RangeQueryError as exc:
        logger.warning(
            "api_range_multi.validation_error detail=%s params=%s",
            exc,
            format_payload(params_dict),
        )
        return jsonify({"ok": False, "error": "invalid-parameters", "detail": str(exc)}), 422

    backend = (cfg.data_backend or "legacy").lower()
    if backend != "supabase":
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "range-multi-requires-supabase",
                    "detail": "set DATA_BACKEND=supabase for batch range",
                }
            ),
            501,
        )

    provider = _supabase_provider(cfg)
    if provider is None:
        logger.warning("api_range_multi.supabase_missing_config")
        return jsonify({"ok": False, "error": "supabase-unavailable"}), 502

    raw_stores = request.args.get("stores") or ""
    slugs = _parse_multi_store_slugs(raw_stores, max_stores=MAX_MULTI_STORES)
    if not slugs:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "missing-or-invalid-stores",
                    "detail": "provide stores=slug1,slug2 (known slugs only)",
                }
            ),
            422,
        )

    # Flask コンテキスト外のワーカースレッドで使えるよう、参照を先に取得
    # （current_app プロキシはワーカースレッドの中では使えないため、cache は
    # 必ずここで実体を取り出しておく。forecast.py の forecast_today_multi と
    # 同じ理由・同じパターン）。
    cache = _range_cache()

    def _fetch_slug(slug: str):
        store_id = SLUG_TO_ID[slug]
        # api_range（単体）と全く同じキー・エンベロープを使うことで、店舗ページの
        # 単体 /api/range とこの range_multi 経路のどちらが先に来ても single-flight
        # で合流し、Supabase への重複クエリを1回にできる（forecast.py の
        # today/today_multi と同じパターン）。
        cache_key = _range_cache_key(store_id, query.start, query.end, query.limit)

        def _compute() -> tuple[tuple[dict, int], bool]:
            # ここに来る時点で backend=="supabase" かつ provider は必ず利用可能
            # （関数冒頭で確認済み）なので、legacy フォールバックには入らない
            # -> gas_client は使われないため None で構わない。
            return _compute_range_for_store(
                cfg=cfg,
                logger=logger,
                backend=backend,
                store_id=store_id,
                query=query,
                provider=provider,
                gas_client=None,
            )

        (body, _http_status), cache_status = cache.get_or_compute(cache_key, _compute)
        if not body.get("ok", True):
            # range_multi は昔から rows キーのみのエラーボディ（error + 空 rows）を
            # 返してきたため、by_slug の形は維持しつつ detail は落とす。
            logger.warning("api_range_multi.supabase_error slug=%s detail=%s", slug, body.get("detail"))
            return slug, {"ok": False, "error": body.get("error", "upstream-supabase"), "rows": []}, cache_status
        return slug, {"rows": body["rows"]}, cache_status

    by_slug: dict[str, dict] = {}
    cache_counts: dict[str, int] = {}
    with ThreadPoolExecutor(max_workers=min(12, len(slugs))) as pool:
        futures = [pool.submit(_fetch_slug, s) for s in slugs]
        for fut in as_completed(futures):
            slug_key, data, cache_status = fut.result()
            by_slug[slug_key] = data
            cache_counts[cache_status] = cache_counts.get(cache_status, 0) + 1

    partial_failure_count = sum(
        1 for data in by_slug.values() if isinstance(data, dict) and not data.get("ok", True)
    )

    logger.info(
        "api_range_multi.success slug_count=%d limit=%d partial_failure_count=%d cache=%s",
        len(slugs),
        query.limit,
        partial_failure_count,
        cache_counts,
    )
    return jsonify({
        "ok": True,
        "by_slug": by_slug,
        "partial_failure_count": partial_failure_count,
    })


def _parse_range_query(cfg: AppConfig) -> RangeQuery:
    raw_from = request.args.get("from")
    raw_to = request.args.get("to")
    raw_limit = request.args.get("limit")

    start = None
    end = None

    if raw_from:
        start = timeutil.parse_ymd(raw_from)
        if start is None:
            raise RangeQueryError("from must be a valid YYYY-MM-DD")

    if raw_to:
        end = timeutil.parse_ymd(raw_to)
        if end is None:
            raise RangeQueryError("to must be a valid YYYY-MM-DD")
    elif raw_from:
        end = start

    if start and end and start > end:
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


# /api/range 系はポーリング頻度が高く、フロントは ts/men/women/total しか使わない
# （useStorePreviewData 等の全消費側で確認済み・詳細は 2026-07 の perf 監査参照）。
# weather_label/src_brand は表示に使われず、store_id は行ごとに重複しても意味がない
# ため、HTTPレスポンス直前にここで落としてペイロードを削減する。
# 注意: provider.fetch_range() の select 自体（weather_code/temp_c/precip_mm を含む）
# は ML 前処理 (ml/preprocess.py) が消費する get_records() 経由の呼び出しとも共有して
# いるため変更しない。ここでのトリムはこのモジュール内のHTTPレスポンス生成箇所のみに
# 適用され、ML学習パスには一切影響しない。
_RANGE_ROW_FIELDS_TO_DROP = ("weather_label", "src_brand", "store_id")


def _trim_range_row(row: dict) -> dict:
    if not any(f in row for f in _RANGE_ROW_FIELDS_TO_DROP):
        return row
    return {k: v for k, v in row.items() if k not in _RANGE_ROW_FIELDS_TO_DROP}


def _trim_range_rows(rows: list[dict]) -> list[dict]:
    return [_trim_range_row(r) for r in rows]


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


def _range_bounds_to_utc(start: date, end: date, tz_name: str) -> tuple[datetime, datetime]:
    tz = timeutil.get_timezone(tz_name)
    start_dt = datetime.combine(start, time.min, tzinfo=tz)
    end_dt = datetime.combine(end, time.max, tzinfo=tz)
    return start_dt.astimezone(timezone.utc), end_dt.astimezone(timezone.utc)
