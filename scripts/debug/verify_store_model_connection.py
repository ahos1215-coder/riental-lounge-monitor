from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from oriental import create_app


def _safe_json(resp):
    try:
        return resp.get_json(silent=True) or {}
    except Exception:  # noqa: BLE001
        return {}


def _extract_signature(points: list[dict]) -> list[tuple[str, float]]:
    sig: list[tuple[str, float]] = []
    for row in points[:5]:
        ts = str(row.get("ts", ""))
        total = float(row.get("total_pred", 0.0) or 0.0)
        sig.append((ts, round(total, 3)))
    return sig


def _sum_abs_signature_diff(left: list[tuple[str, float]], right: list[tuple[str, float]]) -> float:
    if len(left) != len(right):
        return float("inf")
    total = 0.0
    for (lts, lv), (rts, rv) in zip(left, right):
        if lts != rts:
            return float("inf")
        total += abs(lv - rv)
    return round(total, 6)


def main() -> int:
    stores = ["ol_nagasaki", "ol_shibuya"]
    app = create_app()

    with app.app_context():
        from oriental.ml.forecast_service import ForecastService

        service = ForecastService.from_app(app)
        app.config["FORECAST_SERVICE"] = service
        # Optional: force refresh only when explicitly requested
        if os.getenv("FORCE_MODEL_REGISTRY_REFRESH", "0") == "1":
            service.model_registry._next_refresh_unix = 0

        meta = {}
        bundle = service.model_registry.get_bundle(store_id=stores[0])
        meta = bundle.metadata
        store_models = meta.get("store_models") if isinstance(meta, dict) else None
        print("=== metadata ===")
        print(
            json.dumps(
                {
                    "schema_version": meta.get("schema_version"),
                    "trained_at": meta.get("trained_at"),
                    "has_store_models_flag": bool(meta.get("has_store_models", False)),
                    "has_store_models": isinstance(store_models, dict),
                    "store_models_count": len(store_models) if isinstance(store_models, dict) else 0,
                    "sample_stores": sorted(list(store_models.keys()))[:10] if isinstance(store_models, dict) else [],
                },
                ensure_ascii=False,
                indent=2,
            )
        )

        client = app.test_client()
        results: dict[str, dict] = {}
        for store in stores:
            resp = client.get(f"/api/forecast_today?store={store}")
            body = _safe_json(resp)
            points = body.get("data", []) if isinstance(body.get("data"), list) else []
            reasoning = body.get("reasoning", {}) if isinstance(body.get("reasoning"), dict) else {}
            notes = reasoning.get("notes", []) if isinstance(reasoning.get("notes"), list) else []

            results[store] = {
                "status_code": resp.status_code,
                "points": len(points),
                "notes": notes,
                "signature": _extract_signature(points),
            }

        print("=== response check ===")
        print(json.dumps(results, ensure_ascii=False, indent=2))

        nagasaki_notes = " ".join(results["ol_nagasaki"]["notes"])
        shibuya_notes = " ".join(results["ol_shibuya"]["notes"])

        same_signature = (
            results["ol_nagasaki"]["signature"] == results["ol_shibuya"]["signature"]
            and results["ol_nagasaki"]["points"] > 0
            and results["ol_shibuya"]["points"] > 0
        )
        signature_diff_sum = _sum_abs_signature_diff(
            results["ol_nagasaki"]["signature"],
            results["ol_shibuya"]["signature"],
        )

        print("=== assertions ===")
        print(f"metadata_has_store_models_flag={bool(meta.get('has_store_models', False))}")
        print(f"metadata_store_models_parsed={isinstance(store_models, dict)}")
        print(f"nagasaki_note_contains_store_name={'ol_nagasaki' in nagasaki_notes}")
        print(f"both_status_200={results['ol_nagasaki']['status_code'] == 200 and results['ol_shibuya']['status_code'] == 200}")
        print(f"both_have_points={results['ol_nagasaki']['points'] > 0 and results['ol_shibuya']['points'] > 0}")
        print(f"predictions_are_identical={same_signature}")
        print(f"signature_abs_diff_sum={signature_diff_sum}")
        print(f"signature_abs_diff_is_positive={signature_diff_sum > 0.0}")
        print(f"notes_are_identical={nagasaki_notes == shibuya_notes}")

        passed = (
            bool(meta.get("has_store_models", False))
            and isinstance(store_models, dict)
            and results["ol_nagasaki"]["status_code"] == 200
            and results["ol_shibuya"]["status_code"] == 200
            and results["ol_nagasaki"]["points"] > 0
            and results["ol_shibuya"]["points"] > 0
            and signature_diff_sum > 0.0
        )
        print("=== final ===")
        print(f"result={'PASS' if passed else 'FAIL'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

