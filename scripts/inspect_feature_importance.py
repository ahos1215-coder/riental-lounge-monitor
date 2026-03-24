from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from oriental.ml.model_registry import ForecastModelRegistry
from oriental.ml.preprocess import FEATURE_COLUMNS


def _top10(score: dict[str, float], feature_columns: list[str]) -> list[tuple[str, float]]:
    fmap = {f"f{i}": name for i, name in enumerate(feature_columns)}
    ranked = [(fmap.get(key, key), float(val)) for key, val in score.items()]
    ranked.sort(key=lambda x: x[1], reverse=True)
    return ranked[:10]


def main() -> int:
    registry = ForecastModelRegistry(
        supabase_url=os.getenv("SUPABASE_URL", "").strip().rstrip("/"),
        service_role_key=(
            os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
            or os.getenv("SUPABASE_SERVICE_KEY", "").strip()
        ),
        bucket=os.getenv("FORECAST_MODEL_BUCKET", "ml-models").strip(),
        model_prefix=os.getenv("FORECAST_MODEL_PREFIX", "forecast/latest").strip("/"),
        cache_dir=Path(os.getenv("FORECAST_MODEL_CACHE_DIR", "data/ml_models")),
        refresh_sec=300,
        schema_version=os.getenv("FORECAST_MODEL_SCHEMA_VERSION", "v1").strip(),
        logger=logging.getLogger("feature-importance"),
    )
    target_store = os.getenv("ML_TRAIN_STORE_ID", "").strip() or os.getenv("STORE_ID", "ol_nagasaki").strip()
    bundle = registry.get_bundle(store_id=target_store)

    men_score = bundle.model.model_men.get_booster().get_score(importance_type="gain")
    women_score = bundle.model.model_women.get_booster().get_score(importance_type="gain")
    men_top10 = _top10(men_score, FEATURE_COLUMNS)
    women_top10 = _top10(women_score, FEATURE_COLUMNS)

    print("MEN_TOP10")
    for idx, (name, gain) in enumerate(men_top10, start=1):
        print(f"{idx}. {name}: {gain:.6f}")

    print("WOMEN_TOP10")
    for idx, (name, gain) in enumerate(women_top10, start=1):
        print(f"{idx}. {name}: {gain:.6f}")

    metadata_path = registry.cache_dir / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    match = metadata.get("feature_columns") == FEATURE_COLUMNS
    print("FEATURE_COLUMNS_MATCH", match)
    print("META_COUNT", len(metadata.get("feature_columns", [])))
    print("PREPROCESS_COUNT", len(FEATURE_COLUMNS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
