"""GitHub Actions ワークフローの「記述と実態の一致」を守る番犬（B-09 / B-10 / B-12）。

守りたいこと:
  1) 全ワークフローが YAML として読めること（コメント整理で構文を壊さない）。
  2) ワークフローのコメントに具体的なローカル LLM モデル名を書かないこと。
     モデル名の正本は scripts/_ollama_common.py の MODEL 定数だけ。過去に
     gemma4:12b -> gemma4:e4b の変更でコメント側が5本取り残された（CLAUDE.md 罠#6）。
  3) 緊急用 generate-weekly-insights.yml が、2026-07-18 に退役した
     集約インデックスファイルを再生成しないこと
     （手動実行するたびに死蔵ファイルが復活してしまうため）。
  4) forecast-accuracy-track.yml の Decide ステップが、既に削除された
     snapshot cron("10 9 * * *")への到達不能分岐を持たないこと。
  5) 監視ワークフロー3本が Python 本文を YAML に埋め戻さないこと
     （判定ロジックは scripts/monitor/*.py にあり、テストで守れる状態を保つ）。
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"


def _workflow_files() -> list[Path]:
    return sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))


def test_全ワークフローがyamlとして読める() -> None:
    files = _workflow_files()
    assert files, "workflow が1本も見つからない（パス誤り）"
    for path in files:
        yaml.safe_load(path.read_text(encoding="utf-8"))


def test_ワークフローに具体的なollamaモデル名を書かない() -> None:
    """モデル名の正本は scripts/_ollama_common.py の MODEL 定数のみ。

    `local_gemma_daily` のような Supabase の source 値（データ）は対象外。
    禁止するのは `gemma4:e4b` 形式のタグ付きモデル名だけ。
    """
    offenders: list[str] = []
    for path in _workflow_files():
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"\bgemma\d+:\S+", text):
            offenders.append(f"{path.name}: {match.group(0)}")
    assert offenders == [], f"ワークフローに具体モデル名が残っている: {offenders}"


def test_本番モデル名の正本は_ollama_commonのMODEL定数() -> None:
    """モデル名のリテラルは scripts/_ollama_common.py の1箇所だけに置く。"""
    text = (REPO_ROOT / "scripts" / "_ollama_common.py").read_text(encoding="utf-8")
    assert re.search(r'^MODEL = "gemma4:e4b"$', text, flags=re.MULTILINE)

    # 日次・週次は共通定数を参照するだけ（コード上のモデル名リテラルを持たない。
    # 経緯を説明する地の文のコメントは対象外なので、クォート付きの文字列だけを見る）。
    for name in ("local_report_job.py", "generate_weekly_insights.py"):
        body = (REPO_ROOT / "scripts" / name).read_text(encoding="utf-8")
        assert not re.search(r'"gemma\d+:[^"]+"', body), f"{name} にモデル名リテラルが残っている"


def test_週次緊急ワークフローはindex_jsonを触らない() -> None:
    text = (WORKFLOWS / "generate-weekly-insights.yml").read_text(encoding="utf-8")
    assert "index.json" not in text
    assert "--skip-index" not in text


def test_精度追跡ワークフローのdecideに到達不能なsnapshot分岐が無い() -> None:
    text = (WORKFLOWS / "forecast-accuracy-track.yml").read_text(encoding="utf-8")
    # 2026-07-18 に snapshot cron("10 9 * * *")を削除済み。github.event.schedule は
    # on.schedule に列挙された文字列しか入らないため、この比較は構造的に到達不能。
    assert "10 9 * * *" not in text
    # 既定は score のまま（workflow_dispatch の inputs.mode 指定時のみ上書き）。
    assert 'MODE="score"' in text


def test_精度追跡ワークフローのscheduleは採点の1本だけ() -> None:
    doc = yaml.safe_load((WORKFLOWS / "forecast-accuracy-track.yml").read_text(encoding="utf-8"))
    triggers = doc.get("on") if "on" in doc else doc.get(True)
    crons = [entry["cron"] for entry in (triggers or {}).get("schedule") or []]
    assert crons == ["10 21 * * *"]


MONITOR_WORKFLOWS = {
    "check-daily-published.yml": "scripts/monitor/check_daily_published.py",
    "check-weekly-published.yml": "scripts/monitor/check_weekly_published.py",
    "check-collection-heartbeat.yml": "scripts/monitor/check_collection_heartbeat.py",
}


def test_監視ワークフローはPythonを埋め込まずスクリプトを呼ぶ() -> None:
    """判定ロジックは scripts/monitor/*.py にあり、テストで守れる状態に保つ（B-10）。"""
    for name, script in MONITOR_WORKFLOWS.items():
        text = (WORKFLOWS / name).read_text(encoding="utf-8")
        assert "<<'PY'" not in text, f"{name} に Python ヒアドキュメントが復活している"
        assert f"python3 {script}" in text, f"{name} が {script} を呼んでいない"
        assert (REPO_ROOT / script).is_file()
