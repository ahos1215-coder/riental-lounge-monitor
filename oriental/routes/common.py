"""Shared helpers for Flask route modules.

`_config()`, `_supabase_provider()`, `_resolve_store_id()` が 4 ファイルに
重複していたため、ここに集約する。

公開 `/api/*` の IP 単位レート制限（`InProcessRateLimiter` / `register_api_rate_limit`）も
ここに置く。実際の app への配線は `oriental/__init__.py::create_app` が行う。
"""

from __future__ import annotations

import threading
import time

from flask import current_app, jsonify, request

from ..config import AppConfig
from ..data.provider import SupabaseLogsProvider


def get_config() -> AppConfig:
    """Return the application config from the Flask app context."""
    return current_app.config["APP_CONFIG"]


def get_supabase_provider(cfg: AppConfig) -> SupabaseLogsProvider | None:
    """Return a cached SupabaseLogsProvider, or None if not configured."""
    if not (cfg.supabase_url and cfg.supabase_service_role_key):
        return None
    if "SUPABASE_PROVIDER" not in current_app.config:
        current_app.config["SUPABASE_PROVIDER"] = SupabaseLogsProvider(
            base_url=cfg.supabase_url,
            api_key=cfg.supabase_service_role_key,
            session=current_app.config.get("HTTP_SESSION"),
            logger=current_app.logger,
        )
    return current_app.config["SUPABASE_PROVIDER"]


def forecast_model_status() -> dict:
    """予測モデルの読み込み状況（/healthz と /api/meta が同じ形で返す）。

    まだ ForecastService が初期化されていない（= 予測を1度も呼んでいない、または
    ENABLE_FORECAST=0）ときは note 付きの「未ロード」を返す。
    """
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


def resolve_store_id(cfg: AppConfig) -> str:
    """Resolve `store` / `store_id` query param to an internal store identifier.

    Lenient: an unknown slug silently falls back to cfg.store_id. This is the
    right behaviour for endpoints where "unresolved -> use configured default"
    is legitimate (/api/forecast_*, /api/second_venues). Do NOT use this for
    single-store data endpoints where an unknown/closed slug must not quietly
    return a different store's data — use resolve_store_id_strict() there.
    """
    from ..utils.stores import resolve_store_identifier

    store_arg = request.args.get("store_id") or request.args.get("store")
    store_id, _ = resolve_store_identifier(store_arg, cfg.store_id)
    return store_id


def resolve_store_id_strict(cfg: AppConfig) -> tuple[str, str] | None:
    """Resolve `store` / `store_id` query param, requiring an exact match
    against a known store slug/id when one is supplied.

    - No `store`/`store_id` query param at all -> falls back to cfg.store_id
      (preserves the historical single-store default behaviour for callers
      that omit the param entirely).
    - An unknown or closed-store slug (e.g. a removed store like sapporo_ag,
      or a nonexistent slug) -> returns None so the caller can respond with a
      clear 404 instead of silently serving cfg.store_id's data under an
      unrelated slug (bug #5, 2026-07 Fable audit).

    Returns (store_id, slug) on success.
    """
    from ..utils.stores import resolve_store_identifier_strict

    store_arg = request.args.get("store_id") or request.args.get("store")
    if not store_arg:
        default_id = cfg.store_id
        return default_id, default_id.split("ol_", 1)[-1]
    return resolve_store_identifier_strict(store_arg)


# ---------- 公開 /api/* の IP 単位レート制限（2026-08-21 外部レビュー F4） ----------
#
# 背景: Render 上の Flask は認証もレート制限も持たないため、Next.js プロキシ側の
# レート制限（frontend/src/lib/api/ の rateLimit）は
# `https://<render-host>/api/range_multi` を直接叩くだけで迂回できた。
# workers=1 / threads=8 の本番では、これで 8 スレッドを飽和させてサイト全体を
# 止められる。ここで「プロセス内メモリの緩い固定窓カウンタ」を入れて底を上げる。
#
# 設計方針:
#   - 対象は `/api/*` のみ。`/healthz` `/readyz` `/tasks/*` `/api/tasks/*` `/static/*`
#     `/`（index）は**対象外**（外形監視と cron を絶対に落とさないため）。
#   - 既存の in-process TTL キャッシュ（routes/_cache.py）と同じくプロセス内メモリ。
#     workers=1 なので実質サーバー全体のカウンタになる。
#   - 状態は app.config に持たせる（モジュールグローバルにしない）。テストで
#     create_app() を何度も作っても互いに干渉しない。
#   - env `API_RATE_LIMIT_ENABLED=0` で完全無効化できる（誤爆時の緊急停止スイッチ）。
#   - 追跡 IP 数に上限を設け、超えたら古い窓から捨てる（メモリ暴走の防止）。
#     Render Starter 512MB の器を自分で圧迫しては本末転倒なため。

_RATE_LIMIT_WINDOW_SEC = 60.0
# 同時に追跡する IP の上限。超過分は窓の古い順に捨てる（fail-open 寄り）。
_RATE_LIMIT_MAX_TRACKED_IPS = 4096

# レート制限を**かけない**パス接頭辞。
#   /healthz, /readyz  … 外形監視（落とすと監視が壊れる）
#   /tasks/, /api/tasks/ … cron-job.org / GHA からの収集タスク（CRON_SECRET 認証済み）
#   /static/           … 静的ファイル
# （`/`（index）や上記以外のパスは、そもそも `/api/` 接頭辞でないので対象外）
_RATE_LIMIT_EXEMPT_PREFIXES = ("/healthz", "/readyz", "/tasks/", "/api/tasks/", "/static/")


class InProcessRateLimiter:
    """IP 単位の固定窓カウンタ（プロセス内メモリ・スレッドセーフ）。

    `limit_per_min` を超えた分だけ False を返す。窓は 60 秒の固定窓で、
    厳密なトークンバケットではない（境界で最大 2 倍まで通る）が、目的は
    「1クライアントが無制限にワーカースレッドを占有すること」の防止なので
    この粒度で十分。
    """

    __slots__ = ("_limit", "_max_tracked", "_lock", "_buckets")

    def __init__(self, limit_per_min: int, max_tracked_ips: int = _RATE_LIMIT_MAX_TRACKED_IPS) -> None:
        self._limit = max(1, int(limit_per_min))
        self._max_tracked = max(16, int(max_tracked_ips))
        self._lock = threading.Lock()
        # key -> [window_start_epoch, count]
        self._buckets: dict[str, list[float]] = {}

    @property
    def limit(self) -> int:
        return self._limit

    def check(self, key: str, now: float | None = None) -> tuple[bool, int]:
        """(許可するか, Retry-After 秒) を返す。"""
        ts = time.monotonic() if now is None else now
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None or ts - bucket[0] >= _RATE_LIMIT_WINDOW_SEC:
                if bucket is None and len(self._buckets) >= self._max_tracked:
                    self._evict_locked(ts)
                self._buckets[key] = [ts, 1.0]
                return True, 0
            if bucket[1] >= self._limit:
                retry_after = max(1, int(_RATE_LIMIT_WINDOW_SEC - (ts - bucket[0])) + 1)
                return False, retry_after
            bucket[1] += 1.0
            return True, 0

    def _evict_locked(self, now: float) -> None:
        """期限切れの窓を落とし、それでも上限を超えるなら古い順に捨てる。"""
        expired = [k for k, v in self._buckets.items() if now - v[0] >= _RATE_LIMIT_WINDOW_SEC]
        for k in expired:
            del self._buckets[k]
        overflow = len(self._buckets) - self._max_tracked + 1
        if overflow > 0:
            oldest = sorted(self._buckets.items(), key=lambda kv: kv[1][0])[:overflow]
            for k, _ in oldest:
                del self._buckets[k]


def client_ip() -> str:
    """レート制限のキーに使うクライアント IP。

    **`X-Forwarded-For` の「先頭」を使ってはいけない**（2026-08-21）。先頭は元クライアントが
    自由に詐称できるヘッダなので、`X-Forwarded-For: <毎回ランダム>` を付けるだけで
    レート制限を丸ごと素通りできてしまう。XFF は各プロキシが「自分が受け取った相手の IP」を
    **末尾に追記**していく仕様なので、**最後の要素 = Render が実際に見た接続元**が
    唯一信用できる値になる。ここではそれをキーにする。

    注意（意図的な仕様）: 通常の利用者トラフィックは Vercel の Next.js プロキシ経由で来るため、
    Render から見た接続元は Vercel の egress IP になる＝**利用者全員が1つのバケットを共有**する。
    それでよい。ここで守りたいのは「Backend を直接叩いて高コスト API を連打される」ケース
    （外部レビューF4）であり、その直叩き側は各自の実 IP で別バケットになる。
    共有バケット側が詰まるのを避けるため、上限は実トラフィックに対して十分大きく取ってある。

    ヘッダが無いローカル実行やテストでは `remote_addr` にフォールバックする。
    """
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        if parts:
            return parts[-1]
    return request.remote_addr or "unknown"


def is_rate_limited_path(path: str) -> bool:
    """このパスをレート制限の対象にするか（`/api/*` のみ・除外接頭辞を優先）。"""
    for prefix in _RATE_LIMIT_EXEMPT_PREFIXES:
        if path.startswith(prefix):
            return False
    return path.startswith("/api/")


def register_api_rate_limit(app, cfg: AppConfig) -> None:
    """`/api/*` に IP 単位のレート制限を before_request として仕掛ける。

    `cfg.api_rate_limit_enabled` が False（env `API_RATE_LIMIT_ENABLED=0`）のときは
    フックそのものを登録しない＝挙動は導入前と完全に同一になる。
    """
    if not cfg.api_rate_limit_enabled:
        app.logger.info("api_rate_limit.disabled")
        return

    limiter = InProcessRateLimiter(cfg.api_rate_limit_per_min)
    app.config["API_RATE_LIMITER"] = limiter
    app.logger.info("api_rate_limit.enabled per_min=%d", limiter.limit)

    @app.before_request
    def _enforce_api_rate_limit():
        if not is_rate_limited_path(request.path):
            return None
        allowed, retry_after = limiter.check(client_ip())
        if allowed:
            return None
        app.logger.warning("api_rate_limit.blocked path=%s", request.path)
        # /api/* の既存エラー形式（ok:false + error）に合わせる。
        resp = jsonify({
            "ok": False,
            "error": "rate-limited",
            "detail": f"too many requests (limit {limiter.limit}/min per IP)",
        })
        resp.status_code = 429
        resp.headers["Retry-After"] = str(retry_after)
        return resp
