"""GitHub Actions ワークフローのスケジュール周りのガード（回帰テスト）。

1) train-ml-model.yml
   日次(UTC 20:30)と週次 Optuna(UTC 日曜 22:00)は日曜に 1.5 時間差で走る。
   日次が長引くと重なり、同じ Supabase logs / Storage forecast/latest/* を
   同時に読み書きして学習結果を奪い合う。workflow レベルの concurrency で
   直列化する（cancel-in-progress: false = 後発は待つ。学習をスキップさせない）。

2) cleanup-old-logs.yml
   冒頭コメントが旧スケジュール（月曜 07:00 JST）のまま残り、実 cron
   （UTC 日曜 05:00 = JST 日曜 14:00）と食い違っていた。コメントと cron の
   整合を固定する。

YAML の `on:` キーは PyYAML が真偽値 True に解決するため、両方のキーを見る。
"""

from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"


def _load(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def _triggers(doc: dict) -> dict:
    return doc.get("on") if "on" in doc else doc.get(True)


def _crons(doc: dict) -> list[str]:
    schedule = (_triggers(doc) or {}).get("schedule") or []
    return [entry["cron"] for entry in schedule]


def test_train_ml_model_is_serialized_by_concurrency():
    doc = _load("train-ml-model.yml")
    concurrency = doc.get("concurrency")
    assert concurrency, "train-ml-model.yml に workflow レベルの concurrency が無い"
    assert concurrency["group"] == "train-ml-model"
    # 後発をキャンセルすると日次 or 週次の学習がまるごと落ちるため必ず false
    assert concurrency["cancel-in-progress"] is False


def test_train_ml_model_keeps_daily_and_weekly_schedules():
    """concurrency 追加でスケジュール自体が変わっていないこと。"""
    assert _crons(_load("train-ml-model.yml")) == ["30 20 * * *", "0 22 * * 0"]


def test_cleanup_old_logs_header_comment_matches_actual_cron():
    path = WORKFLOWS / "cleanup-old-logs.yml"
    text = path.read_text(encoding="utf-8")
    header = "\n".join(text.splitlines()[:6])

    assert _crons(yaml.safe_load(text)) == ["0 5 * * 0"]
    # UTC 日曜 05:00 = JST 日曜 14:00
    assert "日曜 14:00 JST" in header
    assert "UTC 日曜 05:00" in header
    # 旧スケジュールの記述が残っていないこと
    assert "毎週月曜 07:00 JST" not in header
