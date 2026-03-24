from __future__ import annotations

import json
import sys
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from oriental import create_app


def _print_header(title: str) -> None:
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


def _list_storage_objects(*, supabase_url: str, service_key: str, bucket: str, prefix: str) -> list[str]:
    endpoint = f"{supabase_url.rstrip('/')}/storage/v1/object/list/{bucket}"
    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "prefix": prefix.strip("/"),
        "limit": 200,
        "offset": 0,
        "sortBy": {"column": "name", "order": "desc"},
    }
    resp = requests.post(endpoint, headers=headers, json=payload, timeout=30)
    if not resp.ok:
        raise RuntimeError(f"storage list failed status={resp.status_code} body={resp.text[:400]}")
    rows = resp.json()
    if not isinstance(rows, list):
        raise RuntimeError("storage list payload is not list")
    names: list[str] = []
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("name"), str):
            names.append(row["name"])
    return names


def main() -> int:
    target_store = "ol_nagasaki"
    app = create_app()
    cfg = app.config["APP_CONFIG"]

    _print_header("Config")
    print(
        json.dumps(
            {
                "store_id": target_store,
                "data_backend": cfg.data_backend,
                "enable_forecast": cfg.enable_forecast,
                "forecast_model_bucket": cfg.forecast_model_bucket,
                "forecast_model_prefix": cfg.forecast_model_prefix,
                "forecast_model_cache_dir": str(cfg.forecast_model_cache_dir),
                "forecast_model_schema_version": cfg.forecast_model_schema_version,
                "supabase_url_set": bool(cfg.supabase_url),
                "supabase_key_set": bool(cfg.supabase_service_role_key),
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    _print_header("Storage Object Check")
    try:
        names = _list_storage_objects(
            supabase_url=cfg.supabase_url,
            service_key=cfg.supabase_service_role_key,
            bucket=cfg.forecast_model_bucket,
            prefix=cfg.forecast_model_prefix,
        )
        print(f"objects_found={len(names)}")
        for name in names[:50]:
            print(f" - {name}")
        expected = [
            f"model_{target_store}_men.json",
            f"model_{target_store}_women.json",
            "metadata.json",
        ]
        for e in expected:
            ok = e in names
            print(f"[exists] {e}: {ok}")
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] failed to list storage objects: {exc}")

    _print_header("Model Registry Debug")
    with app.app_context():
        service = app.config.get("FORECAST_SERVICE")
        if service is None:
            from oriental.ml.forecast_service import ForecastService

            service = ForecastService.from_app(app)
            app.config["FORECAST_SERVICE"] = service

        registry = service.model_registry
        if registry is None:
            print("[error] model_registry is None")
            return 1

        print(f"cache_dir={registry.cache_dir}")
        print(f"bucket={registry.bucket}")
        print(f"prefix={registry.model_prefix}")

        # Date parsing sanity check
        samples = [
            f"model_{target_store}_20260323_men.json",
            f"model_{target_store}_20260324_men.json",
            f"model_{target_store}_men.json",
        ]
        picked = registry._pick_latest_model_name(samples)  # debug only
        print(f"[date_pick_test] picked={picked}")

        # Try loading bundle and print metadata hints
        try:
            bundle = registry.get_bundle(store_id=target_store)
            print("[ok] registry.get_bundle succeeded")
            print(
                json.dumps(
                    {
                        "trained_at": bundle.metadata.get("trained_at"),
                        "schema_version": bundle.metadata.get("schema_version"),
                        "artifacts_date": bundle.metadata.get("artifacts_date"),
                        "store_models_keys": sorted(
                            list((bundle.metadata.get("store_models") or {}).keys())
                        )[:20],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[error] registry.get_bundle failed: {exc}")
            cache_files = sorted([p.name for p in Path(registry.cache_dir).glob("*") if p.is_file()])
            print(f"[cache_files] {cache_files}")

        _print_header("Forecast API Dry Run")
        result = service.forecast_today(store_id=target_store, freq_min=15, start_h=19, end_h=5)
        print(
            json.dumps(
                {
                    "ok": result.get("ok"),
                    "error": result.get("error"),
                    "detail": result.get("detail"),
                    "points": len(result.get("data", [])) if isinstance(result.get("data"), list) else None,
                    "reasoning": result.get("reasoning"),
                },
                ensure_ascii=False,
                indent=2,
            )
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

