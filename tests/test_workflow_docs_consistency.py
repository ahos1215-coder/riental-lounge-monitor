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
  6) 監視ワークフローの env キー集合が、呼ぶスクリプトの読むキーを取りこぼさないこと
     （取りこぼすと「監視が黙る」だけで気付けない）。
  7) `OPS_NOTIFY_WEBHOOK_URL` を渡すワークフローは `OPS_NOTIFY_WEBHOOK_TYPE` も渡すこと
     （Discord 運用のとき Slack 形式で POST して通知が静かに落ちるのを防ぐ）。
  8) 正本ドキュメント（docs/LOCAL_LLM_SETUP.md / plan/ARCHITECTURE.md）が、退役した
     「モデル名の正本＝local_report_job.py」「experiments/local_llm_spike を import」
     という記述に戻らないこと。
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
    # 2026-08-22 重み凍結(F-5): hash不変監視。restore は workflow_dispatch 専用
    "check-blend-weights-freeze.yml": "scripts/monitor/check_blend_weights_freeze.py",
}


def test_監視ワークフローはPythonを埋め込まずスクリプトを呼ぶ() -> None:
    """判定ロジックは scripts/monitor/*.py にあり、テストで守れる状態に保つ（B-10）。"""
    for name, script in MONITOR_WORKFLOWS.items():
        text = (WORKFLOWS / name).read_text(encoding="utf-8")
        assert "<<'PY'" not in text, f"{name} に Python ヒアドキュメントが復活している"
        assert f"python3 {script}" in text, f"{name} が {script} を呼んでいない"
        assert (REPO_ROOT / script).is_file()


# --------------------------------------------------------------------------- #
# 6) WF の env キー集合 ⊇ スクリプトが読む環境変数キー集合
# --------------------------------------------------------------------------- #
# スクリプト側で読むが WF が渡さなくてよいキー（GitHub Actions が自動で入れるもの・
# ローカル実行専用のもの）。ここに足すときは「渡さなくても監視が黙らないか」を確認すること。
_ENV_KEYS_NOT_FROM_WORKFLOW = {
    "GITHUB_OUTPUT",   # runner が常に設定する
    "GITHUB_ENV",
    "GITHUB_STEP_SUMMARY",
}


def _env_keys_read_by(script_path: Path) -> set[str]:
    """`os.environ.get("X")` / `os.getenv("X")` で読むキー名を集める。"""
    text = script_path.read_text(encoding="utf-8")
    return set(re.findall(r'os\.(?:environ\.get|getenv)\(\s*"([A-Z0-9_]+)"', text))


def _env_keys_provided_by(workflow_path: Path) -> set[str]:
    """WF 内の全 `env:` ブロックのキー名を集める（job/step どこにあっても拾う）。"""
    doc = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    keys: set[str] = set()

    def walk(node) -> None:
        if isinstance(node, dict):
            env = node.get("env")
            if isinstance(env, dict):
                keys.update(str(k) for k in env)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(doc)
    return keys


def test_監視ワークフローはスクリプトが読む環境変数を全部渡す() -> None:
    """WF が env を1つ渡し忘れても監視は「静かに既定値で緑」になり気付けない。"""
    missing: list[str] = []
    for name, script in MONITOR_WORKFLOWS.items():
        wanted = _env_keys_read_by(REPO_ROOT / script) - _ENV_KEYS_NOT_FROM_WORKFLOW
        provided = _env_keys_provided_by(WORKFLOWS / name)
        for key in sorted(wanted - provided):
            missing.append(f"{name} が {script} の {key} を渡していない")
    assert missing == [], missing


# --------------------------------------------------------------------------- #
# 7) OPS 通知は URL と TYPE をセットで渡す
# --------------------------------------------------------------------------- #
def test_OPS通知URLを渡すワークフローはTYPEも渡す() -> None:
    """scripts/_ops_notify.py の既定は Slack 形式。Discord 運用のとき TYPE を渡さないと
    `{"text":...}` を POST して拒否され、アラートが静かに消える（B-03 の穴）。"""
    offenders: list[str] = []
    for path in _workflow_files():
        keys = _env_keys_provided_by(path)
        # notify-on-failure.yml だけは WEBHOOK_URL / WEBHOOK_TYPE という別名で受ける。
        has_url = "OPS_NOTIFY_WEBHOOK_URL" in keys or "WEBHOOK_URL" in keys
        has_type = "OPS_NOTIFY_WEBHOOK_TYPE" in keys or "WEBHOOK_TYPE" in keys
        if has_url and not has_type:
            offenders.append(path.name)
    assert offenders == [], f"OPS_NOTIFY_WEBHOOK_TYPE を渡していない: {offenders}"


# --------------------------------------------------------------------------- #
# 8) 正本ドキュメントが退役した記述に戻らない
# --------------------------------------------------------------------------- #
_MODEL_SOT_DOCS = [
    Path("docs") / "LOCAL_LLM_SETUP.md",
    Path("plan") / "ARCHITECTURE.md",
]


def test_正本ドキュメントがローカルLLMの旧構成を語らない() -> None:
    """CLAUDE.md 罠#6 と正面衝突する記述を禁じる。

    実態: モデル名の正本は scripts/_ollama_common.py の MODEL 定数、日次が import
    するのも同ファイル（`experiments/local_llm_spike.py` ではない）。
    """
    offenders: list[str] = []
    for rel in _MODEL_SOT_DOCS:
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), start=1):
            # 「local_report_job.py の MODEL 定数が正本」と読める記述
            if "モデル名の正本" in line and "_ollama_common" not in line:
                offenders.append(f"{rel.as_posix()}:{line_no} モデル名の正本の記述が古い")
            # 「local_llm_spike を import している」と読める記述
            if "local_llm_spike" in line and "import" in line and "以前" not in line:
                offenders.append(f"{rel.as_posix()}:{line_no} local_llm_spike を import と書いている")
    assert offenders == [], offenders
