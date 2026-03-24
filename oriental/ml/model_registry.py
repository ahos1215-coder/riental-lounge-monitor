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


class ModelRegistryError(RuntimeError):
    pass


class ModelSchemaMismatchError(ModelRegistryError):
    pass


@dataclass(slots=True)
class LoadedModelBundle:
    model: ForecastModel
    metadata: dict[str, Any]
    loaded_at_unix: float


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

        self._lock = threading.Lock()
        self._bundles: dict[str, LoadedModelBundle] = {}
        self._next_refresh_unix = 0.0
        self._metadata: dict[str, Any] | None = None
        self._session = requests.Session()

        self.cache_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_app(cls, app) -> "ForecastModelRegistry":
        cfg = app.config["APP_CONFIG"]
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
        )

    def get_bundle(self, store_id: str) -> LoadedModelBundle:
        store_key = (store_id or "").strip()
        if not store_key:
            raise ModelRegistryError("store_id is required for model lookup")
        now = time.time()
        with self._lock:
            if store_key in self._bundles and now < self._next_refresh_unix:
                return self._bundles[store_key]
            bundle = self._refresh_locked(store_key)
            self._bundles[store_key] = bundle
            self._next_refresh_unix = now + self.refresh_sec
            return bundle

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
                    "loaded_at_unix": None,
                    "age_sec": None,
                }
            sample_store = sorted(self._bundles.keys())[0]
            sample_bundle = self._bundles[sample_store]
            return {
                "loaded": True,
                "stores_loaded": sorted(self._bundles.keys()),
                "refresh_sec": self.refresh_sec,
                "next_refresh_in_sec": max(0, int(self._next_refresh_unix - now)),
                "schema_version": sample_bundle.metadata.get("schema_version"),
                "trained_at": sample_bundle.metadata.get("trained_at"),
                "loaded_at_unix": sample_bundle.loaded_at_unix,
                "age_sec": round(max(0.0, now - sample_bundle.loaded_at_unix), 3),
            }

    def _refresh_locked(self, store_id: str) -> LoadedModelBundle:
        self._validate_basic_config()

        metadata_path = self.cache_dir / "metadata.json"
        self._download_to_cache("metadata.json", metadata_path)
        metadata = self._load_metadata(metadata_path)
        self._validate_metadata(metadata)
        self._metadata = metadata

        model_men_name, model_women_name, source = self._resolve_model_names(metadata, store_id)

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
        return LoadedModelBundle(model=model, metadata=metadata, loaded_at_unix=time.time())

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
        for attempt in range(1, self.download_retry + 1):
            try:
                response = self._session.get(url, headers=headers, timeout=self.request_timeout_sec)
                if response.ok:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    dst.write_bytes(response.content)
                    return

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

                raise ModelRegistryError(
                    f"model download failed: object={object_name} url={url} status={response.status_code}"
                )
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
                raise ModelRegistryError(f"model download failed: object={object_name} url={url}") from exc

        # Defensive: 通常到達しないが、型安全のため明示
        raise ModelRegistryError(f"model download failed: object={object_name} url={url}") from last_exc

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
