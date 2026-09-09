from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

# リポジトリルートの .env / .env.local を読み込む（Next 用の .env.local に SUPABASE_* を置ける）
# 順序: 先に .env、次に .env.local で上書き（ローカル秘密を優先）
try:
    _root = Path(__file__).resolve().parent.parent
    _env_base = _root / ".env"
    _env_local = _root / ".env.local"
    if _env_base.is_file():
        load_dotenv(_env_base, override=False)
    if _env_local.is_file():
        load_dotenv(_env_local, override=True)
except Exception as exc:  # pragma: no cover
    print(f"[config] failed to load .env / .env.local: {exc}")


@dataclass(slots=True)
class AppConfig:
    """Centralised configuration loaded from the environment."""

    target_url: str
    store_name: str
    store_id: str
    window_start: int
    window_end: int
    timezone: str
    gs_webhook_url: str
    gs_read_url: str
    supabase_url: str
    supabase_service_role_key: str
    data_backend: str
    log_level: str
    http_timeout: float
    http_retry: int
    user_agent: str
    data_dir: Path
    data_file: Path
    log_file: Path
    max_range_limit: int  # FIX: configurable /api/range upper bound
    max_range_total_rows: int  # 1リクエストで返してよい総行数（stores 数 × limit）の上限
    api_rate_limit_enabled: bool
    api_rate_limit_per_min: int
    forecast_model_bucket: str
    forecast_model_prefix: str
    forecast_model_cache_dir: Path
    forecast_model_refresh_sec: int
    forecast_model_schema_version: str
    enable_forecast: bool

    @classmethod
    def from_env(cls) -> "AppConfig":
        data_dir = Path(os.getenv("DATA_DIR", "data"))
        window_start = _as_int(os.getenv("WINDOW_START", "19"), fallback=19)
        window_end = _as_int(os.getenv("WINDOW_END", "5"), fallback=5)
        http_timeout = float(os.getenv("HTTP_TIMEOUT_S", "12"))
        http_retry = _as_int(os.getenv("HTTP_RETRY", "3"), fallback=3)
        # 既定 6000（旧 50000）: 無認証で叩ける /api/range が limit=50000 まで受理してしまい、
        # 1リクエストで巨大な応答を強制生成できる OOM レバーになっていたため絞る
        # （bug #6, 2026-07 Fable audit）。温め済みの正規経路は最大 1200 行（昨日ビュー）
        # なので 6000 でも十分な余裕がある。env MAX_RANGE_LIMIT で上書き可能なのは維持。
        max_range_limit = _as_int(os.getenv("MAX_RANGE_LIMIT", "6000"), fallback=6000)  # FIX
        # 1リクエストの総返却行数（= 店舗数 × limit）の上限。/api/range_multi は
        # 42店 × 6000行 を無認証で1発要求できてしまい、workers=1/threads=8 の本番を
        # 1リクエストで飽和させられる（2026-08-21 外部レビュー F4）。
        # 正規の呼び出しは最大でも 12店 × 48行 = 576 / 3店 × 200行 = 600 なので
        # 12000 でも 20倍の余裕があり、42×6000=252000 は 21倍下回って弾かれる。
        max_range_total_rows = _as_int(os.getenv("MAX_RANGE_TOTAL_ROWS", "12000"), fallback=12000)
        # IP 単位の緩いレート制限（/api/* のみ。/healthz・/readyz・/tasks/* は対象外）。
        # 誤爆時は Render の環境変数 API_RATE_LIMIT_ENABLED=0 だけで完全停止できる。
        api_rate_limit_enabled = os.getenv("API_RATE_LIMIT_ENABLED", "1").strip() != "0"
        api_rate_limit_per_min = _as_int(os.getenv("API_RATE_LIMIT_PER_MIN", "300"), fallback=300)
        # 既定 10800秒=3時間（旧 900秒=15分）。2026-09-09 egress 削減。
        # モデルは日次学習（GHA train-ml-model.yml, 05:30 JST）で **1日1回しか変わらない**のに、
        # sweep は窓が来るたびに metadata.json（実測 320,848 B）を取り直していた:
        #   900秒 → 86400/900 = 96窓/日 × 320,848 B ≒ 29.4 MiB/日
        #   10800秒 → 86400/10800 = 8窓/日 × 320,848 B ≒ 2.4 MiB/日（-92%）
        # ＝ Supabase 無料枠を焼き切った 2026-09-05〜09 の事故で、起動時 preload の
        # 重複（12.5 MiB/起動1回）より大きかった可能性が高い側。
        #
        # 伝播（学習済みモデルが全42店に行き渡るまで）の計算:
        #   1窓あたりの再パース上限 = MODEL_REFRESH_BATCH（model_registry.py, 既定14）。
        #   ceil(42 / 14) = 3窓 → 最悪 3 × 3時間 = 9時間。
        #   05:30 の学習に対し、遅くとも 14:30 JST には全店が新モデルになる。
        #   サイトのピークは 19:00 以降（夜窓）なので、ピーク前に必ず伝播が終わる＝実害なし。
        #   （batch を旧既定の 10 のままにすると ceil(42/10)=5窓＝15時間で 20:30 になり、
        #     ピークに食い込むため、batch 側も 10→14 に上げた。model_registry.py 参照）
        # 副作用: 取得失敗後の再試行は max(60, refresh_sec//4) なので 225秒 → 2700秒。
        # 失敗中は in-memory の stale bundle で予測を返し続ける（graceful degradation）ため
        # 表示は壊れず、むしろ 402 障害中に取りに行く回数が減る。
        forecast_model_refresh_sec = _as_int(os.getenv("FORECAST_MODEL_REFRESH_SEC", "10800"), fallback=10800)
        enable_forecast = os.getenv("ENABLE_FORECAST", "0").strip() == "1"
        supabase_url = os.getenv("SUPABASE_URL", "")
        supabase_service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SERVICE_KEY", "")
        data_backend = os.getenv("DATA_BACKEND", "supabase").lower().strip() or "supabase"
        store_id = os.getenv("STORE_ID") or os.getenv("SUPABASE_STORE_ID") or "ol_nagasaki"
        forecast_model_cache_dir = Path(os.getenv("FORECAST_MODEL_CACHE_DIR", str(data_dir / "ml_models")))
        data_file_env = os.getenv("DATA_FILE")
        data_file = Path(data_file_env) if data_file_env else data_dir / "data.json"
        if not data_file.exists():
            fallback_plan = Path("plan") / "data.json"
            if fallback_plan.exists():
                data_file = fallback_plan
        return cls(
            target_url=os.getenv("TARGET_URL", "https://oriental-lounge.com/stores/38"),
            store_name=os.getenv("STORE_NAME", "長崎店"),
            store_id=store_id,
            window_start=window_start,
            window_end=window_end,
            timezone=os.getenv("TIMEZONE", "Asia/Tokyo"),
            gs_webhook_url=os.getenv("GS_WEBHOOK_URL", ""),
            gs_read_url=os.getenv("GS_READ_URL", ""),
            supabase_url=supabase_url,
            supabase_service_role_key=supabase_service_role_key,
            data_backend=data_backend,
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            http_timeout=http_timeout,
            http_retry=http_retry,
            user_agent=os.getenv(
                "HTTP_USER_AGENT",
                "OrientalLoungeMonitor/1.0 (+https://oriental-lounge.com)"
            ),
            data_dir=data_dir,
            data_file=data_file,
            log_file=data_dir / "log.jsonl",
            max_range_limit=max_range_limit,
            max_range_total_rows=max_range_total_rows,
            api_rate_limit_enabled=api_rate_limit_enabled,
            api_rate_limit_per_min=api_rate_limit_per_min,
            forecast_model_bucket=os.getenv("FORECAST_MODEL_BUCKET", "ml-models"),
            forecast_model_prefix=os.getenv("FORECAST_MODEL_PREFIX", "forecast/latest"),
            forecast_model_cache_dir=forecast_model_cache_dir,
            forecast_model_refresh_sec=forecast_model_refresh_sec,
            # v7 = total_slope_30min のターゲットリーク修正（再学習必須。旧 v6 モデルは互換なし）
            forecast_model_schema_version=os.getenv("FORECAST_MODEL_SCHEMA_VERSION", "v7"),
            enable_forecast=enable_forecast,
        )

    def _shared_summary(self) -> dict[str, object]:
        """/healthz と /api/meta が共通で返すブロック（両者で必ず同じ値にする）。"""
        return {
            "store": self.store_name,
            "timezone": self.timezone,
            "window": {"start": self.window_start, "end": self.window_end},
            "data_backend": self.data_backend,
            "supabase": {
                "url": bool(self.supabase_url),
                "service_role": bool(self.supabase_service_role_key),
                "store_id": self.store_id,
            },
            "http_timeout": self.http_timeout,
            "http_retry": self.http_retry,
            "max_range_limit": self.max_range_limit,  # FIX
            "forecast_model": {
                "bucket": self.forecast_model_bucket,
                "prefix": self.forecast_model_prefix,
                "refresh_sec": self.forecast_model_refresh_sec,
                "schema_version": self.forecast_model_schema_version,
            },
            "forecast_enabled": self.enable_forecast,
        }

    def health_summary(self) -> dict[str, object]:
        """Summarise runtime config for /healthz（外形監視用に収集設定の有無も返す）。"""
        return {
            **self._shared_summary(),
            "target": bool(self.target_url),
            "gs_webhook": bool(self.gs_webhook_url),
            "gs_read": bool(self.gs_read_url),
        }

    def summary(self) -> dict[str, object]:
        """Summarise runtime config for /api/meta."""
        return {
            **self._shared_summary(),
            "store_id": self.store_id,
        }


def _as_int(raw: str | None, *, fallback: int) -> int:
    if raw is None:
        return fallback  # FIX
    try:
        return int(raw)
    except (TypeError, ValueError):
        return fallback
