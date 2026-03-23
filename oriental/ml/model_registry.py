from __future__ import annotations

import json
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
        logger,
    ) -> None:
        self.supabase_url = supabase_url.rstrip("/")
        self.service_role_key = service_role_key
        self.bucket = bucket.strip("/")
        self.model_prefix = model_prefix.strip("/")
        self.cache_dir = cache_dir
        self.refresh_sec = max(30, int(refresh_sec))
        self.schema_version = schema_version.strip()
        self.logger = logger

        self._lock = threading.Lock()
        self._bundle: LoadedModelBundle | None = None
        self._next_refresh_unix = 0.0
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
            logger=app.logger,
        )

    def get_bundle(self) -> LoadedModelBundle:
        now = time.time()
        with self._lock:
            if self._bundle is not None and now < self._next_refresh_unix:
                return self._bundle
            bundle = self._refresh_locked()
            self._bundle = bundle
            self._next_refresh_unix = now + self.refresh_sec
            return bundle

    def current_status(self) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            bundle = self._bundle
            if bundle is None:
                return {
                    "loaded": False,
                    "refresh_sec": self.refresh_sec,
                    "next_refresh_in_sec": 0,
                    "schema_version": None,
                    "trained_at": None,
                    "loaded_at_unix": None,
                    "age_sec": None,
                }
            return {
                "loaded": True,
                "refresh_sec": self.refresh_sec,
                "next_refresh_in_sec": max(0, int(self._next_refresh_unix - now)),
                "schema_version": bundle.metadata.get("schema_version"),
                "trained_at": bundle.metadata.get("trained_at"),
                "loaded_at_unix": bundle.loaded_at_unix,
                "age_sec": round(max(0.0, now - bundle.loaded_at_unix), 3),
            }

    def _refresh_locked(self) -> LoadedModelBundle:
        self._validate_basic_config()

        metadata_path = self.cache_dir / "metadata.json"
        self._download_to_cache("metadata.json", metadata_path)
        metadata = self._load_metadata(metadata_path)
        self._validate_metadata(metadata)

        model_men_name = str(metadata.get("model_men", "model_men.json"))
        model_women_name = str(metadata.get("model_women", "model_women.json"))

        model_men_path = self.cache_dir / Path(model_men_name).name
        model_women_path = self.cache_dir / Path(model_women_name).name
        self._download_to_cache(model_men_name, model_men_path)
        self._download_to_cache(model_women_name, model_women_path)

        model = ForecastModel.from_files(model_men_path=model_men_path, model_women_path=model_women_path)
        self.logger.info(
            "forecast.model_registry.loaded schema=%s cache_dir=%s",
            metadata.get("schema_version"),
            self.cache_dir,
        )
        return LoadedModelBundle(model=model, metadata=metadata, loaded_at_unix=time.time())

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
        try:
            response = self._session.get(url, headers=headers, timeout=20)
        except Exception as exc:  # noqa: BLE001
            raise ModelRegistryError(f"model download failed: {object_name}") from exc
        if not response.ok:
            raise ModelRegistryError(f"model download failed: {object_name} status={response.status_code}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(response.content)

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
