"""logs テーブルを Supabase 無料プランの DB 容量（500MB）に収める設定の番犬（2026-09-26）。

背景:
  無料プランは DB が 500MB を超えると read-only になり、収集（INSERT）が止まる。猶予期間は
  2026-09-05 の超過で使い切っているので予告は来ない。以前の緊急削除の上限（300万行）は
  約 713MB 相当で、上限に届く前に 500MB を超える＝安全弁として効いていなかった。
  オーナーと合意した対処（「1年保持・超えたら古い順に消す」今までのスタイルを保ったまま数字だけ直す）:
    - 上限を 145万行に下げる（DB に残るのは約9か月半ぶん）
    - 消える前の行は 12週ごとに永久アーカイブ（logs-archive-*）として残す

このテストが落ちたら:
  上限を上げる・アーカイブを外す変更が入った。上限を上げるなら、scripts/cleanup_old_logs.py の
  MAX_ROWS の注記（1行あたり約231B＋固定分約20MB＋autovacuum 待ちの空き約67MB）で 500MB との
  関係を計算し直してから、ここも直すこと。
"""

from __future__ import annotations

import importlib
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

# 9/26 の実測から出した見積もり（scripts/cleanup_old_logs.py の MAX_ROWS 注記と同じ値）。
BYTES_PER_ROW = 231
FIXED_MB = 20
VACUUM_SLACK_MB = 67
ONE_WEEK_ROWS = 5040 * 7  # 週1回の cleanup の間に上限を超えて増える分
DB_LIMIT_MB = 500


def _cleanup_module():
    return importlib.import_module("scripts.cleanup_old_logs")


def _steps(workflow: str, job: str) -> list[dict]:
    doc = yaml.safe_load((WORKFLOWS / workflow).read_text(encoding="utf-8"))
    return doc["jobs"][job]["steps"]


def test_上限の既定値は500MBに収まる() -> None:
    max_rows = _cleanup_module().MAX_ROWS
    peak_mb = FIXED_MB + (max_rows + ONE_WEEK_ROWS) * BYTES_PER_ROW / 1e6 + VACUUM_SLACK_MB
    assert peak_mb <= DB_LIMIT_MB * 0.9, (
        f"LOGS_MAX_ROWS={max_rows:,} だと見込みの最大が {peak_mb:.0f}MB（500MB の90%超）。"
        "無料プランは 500MB を超えると read-only で収集が止まる"
    )


def test_ワークフローの既定値もスクリプトと同じ() -> None:
    max_rows = str(_cleanup_module().MAX_ROWS)
    doc = yaml.safe_load((WORKFLOWS / "cleanup-old-logs.yml").read_text(encoding="utf-8"))
    triggers = doc.get("on") if "on" in doc else doc.get(True)
    assert triggers["workflow_dispatch"]["inputs"]["max_rows"]["default"] == max_rows
    envs = [step.get("env", {}) for job in doc["jobs"].values() for step in job.get("steps", [])]
    fallbacks = [env["LOGS_MAX_ROWS"] for env in envs if "LOGS_MAX_ROWS" in env]
    assert fallbacks and all(f"|| '{max_rows}'" in value for value in fallbacks)


def test_永久アーカイブの工程がある() -> None:
    steps = _steps("backup-logs.yml", "backup")
    names = [step.get("name", "") for step in steps]
    archive = next(step for step in steps if "permanent archive" in step.get("name", ""))
    prune_index = next(i for i, name in enumerate(names) if name.startswith("Prune old backups"))
    # 暗号化して Release に上げた後、古い世代を消す前に撮る
    assert names.index(archive["name"]) < prune_index
    assert "logs-archive-" in archive["run"]
    assert "-lt 84" in archive["run"]  # 12週（84日）に1回
    # 同じ「上流が止まっている間は抑制する」ゲートに従う
    assert archive.get("if") == "steps.quota_gate.outputs.paused != 'true'"


def test_古い世代の削除はアーカイブを消さない() -> None:
    prune = next(step for step in _steps("backup-logs.yml", "backup") if step.get("name", "").startswith("Prune old backups"))
    assert "grep '^logs-backup-'" in prune["run"]
    assert "logs-archive" not in prune["run"]
