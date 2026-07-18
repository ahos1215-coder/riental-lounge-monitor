from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from .model_xgb import ForecastModel
from .preprocess import FEATURE_COLUMNS


def _safe_int(raw: str | None, *, fallback: int) -> int:
    if raw is None:
        return fallback
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return fallback


class ModelRegistryError(RuntimeError):
    pass


class ModelSchemaMismatchError(ModelRegistryError):
    pass


@dataclass(slots=True)
class LoadedModelBundle:
    model: ForecastModel
    metadata: dict[str, Any]
    loaded_at_unix: float
    # ロード時に解決したモデルファイル名 (men, women)。refresh 時にこれと比較し、
    # 名前が同じ＝モデル実体が変わっていなければ再ダウンロード/再パースをスキップする
    # (2026-07-17 メモリ成長事件#2の根治: 旧実装は15分毎に同一モデルを再構築し、
    #  glibc arena 断片化で RSS が単調増加していた。モデル名は日付入りで一意)。
    model_names: tuple[str, str] | None = None


class ForecastModelRegistry:
    """Loads and caches forecast model artifacts from Supabase Storage."""

    def __init__(
        self,
        *,
        supabase_url: str,
        service_role_key: str,
        bucket: str,
        model_prefix: str,
        cache_dir: Path,
        refresh_sec: int,
        schema_version: str,
        request_timeout_sec: float,
        download_retry: int,
        logger,
        cache_max_age_sec: int = 7 * 86400,
        refresh_batch: int = 10,
    ) -> None:
        self.supabase_url = supabase_url.rstrip("/")
        self.service_role_key = service_role_key
        self.bucket = bucket.strip("/")
        self.model_prefix = model_prefix.strip("/")
        self.cache_dir = cache_dir
        self.refresh_sec = max(30, int(refresh_sec))
        self.schema_version = schema_version.strip()
        self.request_timeout_sec = max(3.0, float(request_timeout_sec))
        self.download_retry = max(1, int(download_retry))
        self.logger = logger
        # Disk cache fallback の最大有効期限。これを超えた古いキャッシュは
        # ネットワーク障害時でも fallback として使わない（例外を伝播）。
        self.cache_max_age_sec = max(60, int(cache_max_age_sec))
        # 1ウィンドウあたりに許容する「実再パース」(ダウンロード+LightGBM parse)の上限。
        # 名前チェックそのものは既知の全店舗に対して毎ウィンドウ行う(安価)が、
        # 実体が変わった店舗の再構築はこの件数までに絞り、0.5vCPU上での
        # 再学習直後のCPUスパイクを避ける (Fable監査 Batch B5 bug#7)。
        self.refresh_batch = max(1, int(refresh_batch))

        self._lock = threading.Lock()
        self._bundles: dict[str, LoadedModelBundle] = {}
        self._next_refresh_unix = 0.0
        self._metadata: dict[str, Any] | None = None
        self._last_error: str | None = None
        self._last_error_at_unix: float | None = None
        self._last_refresh_ok_unix: float | None = None
        self._session = requests.Session()

        self.cache_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_app(cls, app) -> "ForecastModelRegistry":
        import os

        cfg = app.config["APP_CONFIG"]
        cache_max_age_sec = _safe_int(
            os.getenv("FORECAST_MODEL_CACHE_MAX_AGE_SEC"),
            fallback=7 * 86400,
        )
        refresh_batch = _safe_int(os.getenv("MODEL_REFRESH_BATCH"), fallback=10)
        return cls(
            supabase_url=cfg.supabase_url,
            service_role_key=cfg.supabase_service_role_key,
            bucket=cfg.forecast_model_bucket,
            model_prefix=cfg.forecast_model_prefix,
            cache_dir=cfg.forecast_model_cache_dir,
            refresh_sec=cfg.forecast_model_refresh_sec,
            schema_version=cfg.forecast_model_schema_version,
            request_timeout_sec=cfg.http_timeout,
            download_retry=cfg.http_retry,
            logger=app.logger,
            cache_max_age_sec=cache_max_age_sec,
            refresh_batch=refresh_batch,
        )

    def get_bundle(self, store_id: str) -> LoadedModelBundle:
        store_key = (store_id or "").strip()
        if not store_key:
            raise ModelRegistryError("store_id is required for model lookup")
        now = time.time()
        with self._lock:
            cached = self._bundles.get(store_key)
            due = now >= self._next_refresh_unix
            if cached is not None and not due:
                return cached
            do_sweep = due
            if due:
                # このウィンドウの「refresh権」を先取りする。ロック保持はここだけ
                # (バンプのみ、瞬時)。実際のダウンロード/パースはロック外で行う
                # (lock-free download)。ほぼ同時に来た他店舗向けリクエストは、
                # このウィンドウでは自分のキャッシュ済み bundle をそのまま返し
                # (無ければ後述の単独ロードへ)、更新は次ウィンドウで拾う。
                self._next_refresh_unix = now + self.refresh_sec

        try:
            if do_sweep:
                metadata, updates, trigger_error = self._sweep_unlocked(store_key)
            else:
                metadata, bundle = self._load_single_unlocked(store_key)
                updates, trigger_error = {store_key: bundle}, None
        except Exception as exc:  # noqa: BLE001 — metadata取得自体が失敗した等、全体が成立しない場合
            return self._record_failure_and_get_stale(store_key, exc, now)

        with self._lock:
            # メタデータ重複排除: 内容が前回と同一なら共有オブジェクトを使い回す。
            # 旧実装は store ごとの refresh で毎回新しい dict をパースして各 bundle が
            # 個別に抱え込み、42店で同一内容のコピーが43部(実測~26MB)常駐していた
            # (2026-07-17 実証班の発見)。内容が変わった時だけ差し替える。
            if self._metadata is not None and metadata == self._metadata:
                metadata = self._metadata
            else:
                self._metadata = metadata
            for sid, bundle in updates.items():
                bundle.metadata = metadata
                self._bundles[sid] = bundle
            if trigger_error is None:
                self._last_error = None
                self._last_error_at_unix = None
                self._last_refresh_ok_unix = now
            result = self._bundles.get(store_key)

        if trigger_error is not None and store_key not in updates:
            # トリガー店舗自体の取得は失敗（他の店舗の伝播は成功していれば上で反映済み）。
            # stale があればそれで graceful degradation、無ければ例外伝播。
            return self._record_failure_and_get_stale(store_key, trigger_error, now)

        assert result is not None
        return result

    def current_status(self) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            if not self._bundles:
                return {
                    "loaded": False,
                    "refresh_sec": self.refresh_sec,
                    "next_refresh_in_sec": 0,
                    "schema_version": None,
                    "trained_at": None,
                    "trained_at_min": None,
                    "trained_at_max": None,
                    "loaded_at_unix": None,
                    "age_sec": None,
                    "loaded_store_count": 0,
                    "last_refresh_ok_unix": self._last_refresh_ok_unix,
                    "last_error": self._last_error,
                    "last_error_at_unix": self._last_error_at_unix,
                }
            stores_loaded = sorted(self._bundles.keys())
            sample_store = stores_loaded[0]
            sample_bundle = self._bundles[sample_store]
            # 店舗ごとに保持している metadata (=最後にその店舗を更新した時点の
            # metadata.json) の trained_at を集計する。ウィンドウ伝播の途中では
            # 店舗ごとに新旧の metadata が混在し得るため、sample_store（アルファベット
            # 先頭の店舗、従来は ay_chiba 固定）の値だけでは「全体で一番古いのはどれだけ
            # 遅れているか」が見えなかった (Fable監査 Batch B5 bug#7)。min/max を追加で
            # 出すことで、propagation が滞留している店舗の有無を healthz から即座に判別できる。
            trained_ats = sorted(
                ta
                for ta in (b.metadata.get("trained_at") for b in self._bundles.values())
                if ta
            )
            return {
                "loaded": True,
                "stores_loaded": stores_loaded,
                "loaded_store_count": len(stores_loaded),
                "refresh_sec": self.refresh_sec,
                "next_refresh_in_sec": max(0, int(self._next_refresh_unix - now)),
                "schema_version": sample_bundle.metadata.get("schema_version"),
                "trained_at": sample_bundle.metadata.get("trained_at"),
                "trained_at_min": trained_ats[0] if trained_ats else None,
                "trained_at_max": trained_ats[-1] if trained_ats else None,
                "loaded_at_unix": sample_bundle.loaded_at_unix,
                "age_sec": round(max(0.0, now - sample_bundle.loaded_at_unix), 3),
                "last_refresh_ok_unix": self._last_refresh_ok_unix,
                "last_error": self._last_error,
                "last_error_at_unix": self._last_error_at_unix,
            }

    def _sweep_unlocked(
        self, trigger_store_id: str
    ) -> tuple[dict[str, Any], dict[str, LoadedModelBundle], Exception | None]:
        """refresh ウィンドウ到来時の一括伝播（ロックを保持せずに行う）。

        metadata.json のダウンロードは1回だけ。既知の全店舗（+ 今回のトリガー店舗）
        に対して「解決されたモデルファイル名が変わったか」を安価にチェックし、
        実体が変わった店舗だけ再ダウンロード/再パースする。旧実装はトリガーに
        なった1店舗しか見ていなかったため、他の41店舗は自分がたまたまトリガーに
        なる次の巡り合わせ（期待値レベルで ~45時間）まで古いモデルのまま取り残さ
        れていた (Fable監査 Batch B5 bug#7)。

        トリガー店舗は常に先頭で処理し、`refresh_batch` の予算制限を受けない
        （今まさにリクエストされている店舗なので、可能な限り最新であるべき）。
        それ以外の店舗の再構築は `refresh_batch` 件/ウィンドウまでに絞り、残りは
        既存 (stale) bundle を維持して次ウィンドウに持ち越す（graceful degradation
        の自然な延長）。
        """
        self._validate_basic_config()

        metadata_path = self.cache_dir / "metadata.json"
        self._download_to_cache("metadata.json", metadata_path)
        metadata = self._load_metadata(metadata_path)
        self._validate_metadata(metadata)

        with self._lock:
            existing_snapshot = dict(self._bundles)

        known_ids = set(existing_snapshot.keys())
        known_ids.add(trigger_store_id)
        ordered = [trigger_store_id] + sorted(sid for sid in known_ids if sid != trigger_store_id)

        updates: dict[str, LoadedModelBundle] = {}
        trigger_error: Exception | None = None
        reparsed = 0

        for store_id in ordered:
            existing_bundle = existing_snapshot.get(store_id)
            try:
                men_name, women_name, source = self._resolve_model_names(metadata, store_id)
            except Exception as exc:  # noqa: BLE001
                if store_id == trigger_store_id:
                    trigger_error = exc
                else:
                    self.logger.warning(
                        "forecast.model_registry.sweep_resolve_failed store=%s detail=%s",
                        store_id,
                        exc,
                    )
                continue

            if existing_bundle is not None and existing_bundle.model_names == (men_name, women_name):
                # 名前不変 -> 実体は変わっていない。再パース不要、既存オブジェクトをそのまま使う。
                updates[store_id] = existing_bundle
                continue

            if reparsed >= self.refresh_batch:
                # このウィンドウでは再構築の予算切れ。トリガー店舗は ordered[0] のため
                # reparsed==0 の時点で必ず処理されており、この分岐に来ることはない。
                # 既存 (stale) bundle はそのまま維持し、次ウィンドウで再試行する。
                self.logger.info(
                    "forecast.model_registry.sweep_batch_deferred store=%s "
                    "(refresh_batch=%d exhausted this window)",
                    store_id,
                    self.refresh_batch,
                )
                continue

            try:
                bundle = self._load_store_bundle(store_id, metadata, men_name, women_name, source)
                updates[store_id] = bundle
                reparsed += 1
            except Exception as exc:  # noqa: BLE001
                if store_id == trigger_store_id:
                    trigger_error = exc
                else:
                    # 既知の店舗である以上、必ず既存 bundle が手元にある（graceful degradation）。
                    self.logger.warning(
                        "forecast.model_registry.sweep_reload_failed store=%s detail=%s",
                        store_id,
                        exc,
                    )
                continue

        return metadata, updates, trigger_error

    def _load_single_unlocked(self, store_id: str) -> tuple[dict[str, Any], LoadedModelBundle]:
        """まだ一度もロードされていない店舗向けの単独ロード（refresh ウィンドウ未到来時）。

        sweep とは異なり他店舗のチェックは行わず、`refresh_batch` の対象にもならない
        （新規店舗の初回ロードを他店舗の再構築予算で遅らせるべきではないため）。
        """
        self._validate_basic_config()

        metadata_path = self.cache_dir / "metadata.json"
        self._download_to_cache("metadata.json", metadata_path)
        metadata = self._load_metadata(metadata_path)
        self._validate_metadata(metadata)

        men_name, women_name, source = self._resolve_model_names(metadata, store_id)
        bundle = self._load_store_bundle(store_id, metadata, men_name, women_name, source)
        return metadata, bundle

    def _load_store_bundle(
        self,
        store_id: str,
        metadata: dict[str, Any],
        model_men_name: str,
        model_women_name: str,
        source: str,
    ) -> LoadedModelBundle:
        """1店舗分のモデルファイルをダウンロード+パースする（ロック非保持・IO/CPU律速）。"""
        model_men_path = self.cache_dir / Path(model_men_name).name
        model_women_path = self.cache_dir / Path(model_women_name).name
        self.logger.info(
            "Loading %s model: %s, %s (store_id=%s)",
            source,
            model_men_name,
            model_women_name,
            store_id,
        )
        self._download_to_cache(model_men_name, model_men_path)
        self._download_to_cache(model_women_name, model_women_path)

        model = ForecastModel.from_files(model_men_path=model_men_path, model_women_path=model_women_path)
        self.logger.info(
            "forecast.model_registry.loaded schema=%s store_id=%s model_men=%s model_women=%s cache_dir=%s",
            metadata.get("schema_version"),
            store_id,
            model_men_name,
            model_women_name,
            self.cache_dir,
        )
        return LoadedModelBundle(
            model=model,
            metadata=metadata,
            loaded_at_unix=time.time(),
            model_names=(model_men_name, model_women_name),
        )

    def _record_failure_and_get_stale(self, store_key: str, exc: Exception, now: float) -> LoadedModelBundle:
        """Graceful degradation: refresh が失敗しても、メモリに前回の bundle が
        あればそれを使い続ける（一過性の Supabase Storage 障害でユーザーの
        予測グラフが消えるのを防ぐ）。次の refresh は早めに再試行する。
        """
        self._last_error = str(exc)
        self._last_error_at_unix = time.time()
        with self._lock:
            stale = self._bundles.get(store_key)
        if stale is not None:
            age_sec = max(0.0, time.time() - stale.loaded_at_unix)
            self.logger.warning(
                "forecast.model_registry.refresh_failed_using_stale_in_memory "
                "store=%s age_sec=%.0f detail=%s",
                store_key,
                age_sec,
                exc,
            )
            with self._lock:
                self._next_refresh_unix = now + max(60, self.refresh_sec // 4)
            return stale
        raise exc

    def _resolve_model_names(self, metadata: dict[str, Any], store_id: str) -> tuple[str, str, str]:
        has_store_models = bool(metadata.get("has_store_models", False))
        store_models = metadata.get("store_models")
        if isinstance(store_models, dict):
            if not has_store_models:
                self.logger.warning(
                    "metadata inconsistency: has_store_models=false but store_models map exists; store-specific resolution will still be attempted"
                )
            entry = store_models.get(store_id)
            if isinstance(entry, dict):
                men_name = self._pick_latest_model_name(
                    [
                        str(entry.get("dated_model_men", "")).strip(),
                        str(entry.get("model_men", "")).strip(),
                    ]
                )
                women_name = self._pick_latest_model_name(
                    [
                        str(entry.get("dated_model_women", "")).strip(),
                        str(entry.get("model_women", "")).strip(),
                    ]
                )
                if men_name and women_name:
                    return men_name, women_name, "store-specific"

            # store_id mismatchのときは詳細を残して即エラー
            available = sorted(k for k in store_models.keys() if isinstance(k, str))
            raise ModelRegistryError(
                f"store model not found for store_id={store_id}; available={available[:20]}"
            )

        if has_store_models:
            raise ModelRegistryError(
                "metadata indicates has_store_models=true but store_models map is missing/invalid"
            )

        # backward compatibility
        model_men_name = str(metadata.get("model_men", "model_men.json"))
        model_women_name = str(metadata.get("model_women", "model_women.json"))
        self.logger.warning(
            "store_models is unavailable; fallback to global models store_id=%s model_men=%s model_women=%s",
            store_id,
            model_men_name,
            model_women_name,
        )
        return model_men_name, model_women_name, "global fallback"

    @staticmethod
    def _pick_latest_model_name(candidates: list[str]) -> str:
        cleaned = [c for c in candidates if c]
        if not cleaned:
            return ""

        def _score(name: str) -> tuple[int, str]:
            match = re.search(r"(20\d{6})", name)
            date_score = int(match.group(1)) if match else 0
            return (date_score, name)

        return max(cleaned, key=_score)

    def _validate_basic_config(self) -> None:
        if not self.supabase_url:
            raise ModelRegistryError("SUPABASE_URL is not set")
        if not self.service_role_key:
            raise ModelRegistryError("SUPABASE_SERVICE_ROLE_KEY is not set")
        if not self.bucket:
            raise ModelRegistryError("FORECAST_MODEL_BUCKET is not set")
        if not self.model_prefix:
            raise ModelRegistryError("FORECAST_MODEL_PREFIX is not set")

    def _object_url(self, object_name: str) -> str:
        path = f"{self.model_prefix}/{object_name}".strip("/")
        return f"{self.supabase_url}/storage/v1/object/{self.bucket}/{path}"

    def _download_to_cache(self, object_name: str, dst: Path) -> None:
        url = self._object_url(object_name)
        headers = {
            "apikey": self.service_role_key,
            "Authorization": f"Bearer {self.service_role_key}",
        }
        last_exc: Exception | None = None
        last_status: int | None = None
        for attempt in range(1, self.download_retry + 1):
            try:
                response = self._session.get(url, headers=headers, timeout=self.request_timeout_sec)
                if response.ok:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    dst.write_bytes(response.content)
                    return

                last_status = response.status_code
                # 5xx / 429 は一時障害としてリトライ
                if response.status_code in {429, 500, 502, 503, 504} and attempt < self.download_retry:
                    self.logger.warning(
                        "model download transient failure: object=%s status=%s attempt=%d/%d",
                        object_name,
                        response.status_code,
                        attempt,
                        self.download_retry,
                    )
                    time.sleep(min(1.5 * attempt, 5.0))
                    continue

                # Non-retryable HTTP — disk cache fallback を試す
                if self._use_disk_fallback(object_name, dst, reason=f"status={response.status_code}"):
                    return
                raise ModelRegistryError(
                    f"model download failed: object={object_name} url={url} status={response.status_code}"
                )
            except ModelRegistryError:
                raise
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt < self.download_retry:
                    self.logger.warning(
                        "model download exception: object=%s attempt=%d/%d detail=%s",
                        object_name,
                        attempt,
                        self.download_retry,
                        exc,
                    )
                    time.sleep(min(1.5 * attempt, 5.0))
                    continue
                # 全リトライ枯渇 — disk cache fallback を試す
                if self._use_disk_fallback(object_name, dst, reason=str(exc)):
                    return
                raise ModelRegistryError(
                    f"model download failed: object={object_name} url={url}"
                ) from exc

        # Defensive: ループから break せず抜けたケース
        if self._use_disk_fallback(object_name, dst, reason="all-attempts-exhausted"):
            return
        raise ModelRegistryError(
            f"model download failed: object={object_name} url={url} status={last_status}"
        ) from last_exc

    def _use_disk_fallback(self, object_name: str, dst: Path, *, reason: str) -> bool:
        """既存のディスクキャッシュが新しければ fallback として採用する。

        一過性のネットワーク障害（Supabase Storage 接続リセット等）で予測 API が
        止まるのを防ぐためのセーフティネット。`cache_max_age_sec` を超えていれば
        fallback は無効化し、本来の例外を呼び出し元に伝播させる。
        """
        if not dst.exists():
            return False
        try:
            age_sec = time.time() - dst.stat().st_mtime
        except OSError:
            return False
        if age_sec > self.cache_max_age_sec:
            self.logger.warning(
                "model download failed and disk cache too old to use: "
                "object=%s age_sec=%.0f max_age_sec=%d reason=%s",
                object_name,
                age_sec,
                self.cache_max_age_sec,
                reason,
            )
            return False
        self.logger.warning(
            "model download failed; using existing disk cache as fallback: "
            "object=%s age_sec=%.0f reason=%s",
            object_name,
            age_sec,
            reason,
        )
        return True

    def _load_metadata(self, path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise ModelRegistryError("metadata.json is invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ModelRegistryError("metadata.json must be an object")
        return payload

    def _validate_metadata(self, metadata: dict[str, Any]) -> None:
        schema_version = str(metadata.get("schema_version", "")).strip()
        if schema_version != self.schema_version:
            raise ModelSchemaMismatchError(
                f"schema_version mismatch expected={self.schema_version} actual={schema_version}"
            )

        feature_columns = metadata.get("feature_columns")
        if not isinstance(feature_columns, list) or any(not isinstance(c, str) for c in feature_columns):
            raise ModelSchemaMismatchError("feature_columns must be string array")
        if feature_columns != FEATURE_COLUMNS:
            raise ModelSchemaMismatchError("feature_columns mismatch")
