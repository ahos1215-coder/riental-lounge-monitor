"""scripts/train_ml_model.py が学習成功後に scripts/cleanup_old_models.py の世代整理を
呼び出す配線（_prune_old_models_best_effort）のユニットテスト。

train_ml_model.py::main() 全体（実際の学習・Supabase fetch を伴う）は対象外 —
_prune_old_models_best_effort() 単体を、cleanup_old_models.run_cleanup をモンキー
パッチして検証する（実ネットワークアクセス無し）。
"""

from __future__ import annotations

import scripts.train_ml_model as train_ml_model
from scripts.cleanup_old_models import CleanupConfig
from scripts.train_ml_model import TrainingConfig, _prune_old_models_best_effort


def _training_cfg(**overrides) -> TrainingConfig:
    base = dict(
        supabase_url="https://example.supabase.co",
        supabase_service_key="dummy-key",
        bucket="ml-models",
        prefix="forecast/latest",
        schema_version="v7",
        timezone="Asia/Tokyo",
        train_days=180,
        train_limit=1_000_000,
        store_id=None,
        sample_weight_peak=1.8,
        sample_weight_rain=1.8,
        optuna_trials=30,
        optuna_enabled=True,
        objective="regression",
        optuna_max_rows=0,
        gate_max_regression_pct=20.0,
        stale_store_days=7.0,
        recency_halflife_days=90.0,
        recency_floor=0.5,
    )
    base.update(overrides)
    return TrainingConfig(**base)


def test_prune_calls_run_cleanup_with_execute_mode_and_correct_config(monkeypatch):
    calls: list[tuple[CleanupConfig, bool]] = []

    def fake_run_cleanup(cleanup_cfg: CleanupConfig, *, dry_run: bool):
        calls.append((cleanup_cfg, dry_run))

    monkeypatch.setattr(train_ml_model, "run_cleanup", fake_run_cleanup)
    monkeypatch.delenv("MODEL_RETENTION_GENERATIONS", raising=False)

    cfg = _training_cfg(bucket="ml-models", prefix="forecast/latest")
    _prune_old_models_best_effort(cfg)

    assert len(calls) == 1
    cleanup_cfg, dry_run = calls[0]
    assert dry_run is False  # daily job must actually prune, not just report
    assert cleanup_cfg.supabase_url == cfg.supabase_url
    assert cleanup_cfg.supabase_key == cfg.supabase_service_key
    assert cleanup_cfg.bucket == "ml-models"
    assert cleanup_cfg.prefix == "forecast/latest"
    assert cleanup_cfg.retention_generations == 7  # default


def test_prune_reads_retention_generations_from_env(monkeypatch):
    calls: list[CleanupConfig] = []

    def fake_run_cleanup(cleanup_cfg: CleanupConfig, *, dry_run: bool):
        calls.append(cleanup_cfg)

    monkeypatch.setattr(train_ml_model, "run_cleanup", fake_run_cleanup)
    monkeypatch.setenv("MODEL_RETENTION_GENERATIONS", "14")

    _prune_old_models_best_effort(_training_cfg())

    assert calls[0].retention_generations == 14


def test_prune_failure_is_swallowed_and_never_raises(monkeypatch, capsys):
    def failing_run_cleanup(cleanup_cfg: CleanupConfig, *, dry_run: bool):
        raise RuntimeError("Storage is having a bad day")

    monkeypatch.setattr(train_ml_model, "run_cleanup", failing_run_cleanup)

    # 学習ジョブ自体を絶対に落とさない — 例外が外に漏れないことがこのテストの本体。
    _prune_old_models_best_effort(_training_cfg())

    captured = capsys.readouterr()
    assert "[train-ml][prune][WARNING]" in captured.out
    assert "Storage is having a bad day" in captured.out


def test_prune_failure_from_systemexit_is_also_swallowed(monkeypatch, capsys):
    # run_cleanup / cfg.validate() は SystemExit を投げることがある（CleanupConfig.validate
    # の必須項目チェック等）。BaseException 系だが、学習ジョブへの伝播は絶対に許さない。
    def failing_run_cleanup(cleanup_cfg: CleanupConfig, *, dry_run: bool):
        raise SystemExit("MODEL_RETENTION_GENERATIONS must be >= 1")

    monkeypatch.setattr(train_ml_model, "run_cleanup", failing_run_cleanup)

    _prune_old_models_best_effort(_training_cfg())

    captured = capsys.readouterr()
    assert "[train-ml][prune][WARNING]" in captured.out
