"""F3/F2 番犬: 収集タスクが「保存できた件数」を見て成功/失敗を分けること。

背景（外部レビュー 2026-08-21 F3）:
`collect_all_once()` は {"stores": 42, "success": 22, "fail": 20, ...} を返すのに、
`_run_collect_background()` はその中身を一切見ず、例外が出なければ status="completed"、
同期モードも常に ok=True を返していた。42店中20店が保存に失敗しても cron からは
「成功」に見え、鮮度監視（最新行の古さ）も残り22店の更新で緑のままになるため、
履歴が静かに欠け続ける。

修正後の契約:
  - 全店成功 -> status="completed" / ok=True
  - 一部失敗 -> status="completed_with_failures" / ok=False
  - 全滅・戻り値が異常 -> status="failed" / ok=False
  - HTTP ステータスコードと既存レスポンスキーは変えない（cron-job.org の再試行挙動を
    変えないため）
  - /tasks/multi_collect/status は last_run（直前の実行）と process_started_at を返す

ネットワークには出ない（collect_all_once を差し替える）。
"""

from __future__ import annotations

import pytest

from oriental import create_app
from oriental.routes import tasks as tasks_mod


@pytest.fixture
def client():
    app = create_app()
    return app.test_client()


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch: pytest.MonkeyPatch):
    """モジュールグローバルのタスク状態をテスト間で持ち越さない。

    CRON_SECRET / RENDER は開発機の .env 由来で入っていることがあるので外す
    （未設定かつ非本番なら _require_cron_secret() は素通り＝テスト互換の既存挙動）。
    """
    for name in ("CRON_SECRET", "RENDER", "RENDER_SERVICE_ID"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("FLASK_ENV", "test")
    tasks_mod._collect_task = {
        "task_id": None, "status": "idle", "started_at": None,
        "completed_at": None, "result": None, "error": None,
    }
    tasks_mod._collect_last_run.update(
        task_id=None, status=None, started_at=None, completed_at=None, result=None, error=None
    )
    yield


class Test件数から成功失敗を決める:
    @pytest.mark.parametrize(
        ("result", "expected"),
        [
            ({"stores": 42, "success": 42, "fail": 0, "duration_sec": 9.9}, ("completed", True)),
            ({"stores": 42, "success": 22, "fail": 20}, ("completed_with_failures", False)),
            ({"stores": 42, "success": 41, "fail": 1}, ("completed_with_failures", False)),
            ({"stores": 42, "success": 0, "fail": 42}, ("failed", False)),
            ({"stores": 0, "success": 0, "fail": 0}, ("failed", False)),  # 対象店なし
            (None, ("failed", False)),
            ("boom", ("failed", False)),
            ({"stores": "x", "success": "y", "fail": "z"}, ("failed", False)),
        ],
    )
    def test_outcome(self, result, expected) -> None:
        assert tasks_mod._collect_outcome(result) == expected


class Test非同期モードの状態:
    def test_全店成功ならcompleted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            tasks_mod, "collect_all_once", lambda: {"stores": 42, "success": 42, "fail": 0}
        )
        tasks_mod._run_collect_background("t1")
        assert tasks_mod._collect_task["status"] == "completed"

    def test_一部失敗はcompletedにしない(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            tasks_mod, "collect_all_once", lambda: {"stores": 42, "success": 22, "fail": 20}
        )
        tasks_mod._run_collect_background("t2")
        assert tasks_mod._collect_task["status"] == "completed_with_failures"
        assert tasks_mod._collect_task["result"]["fail"] == 20

    def test_全滅はfailed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            tasks_mod, "collect_all_once", lambda: {"stores": 42, "success": 0, "fail": 42}
        )
        tasks_mod._run_collect_background("t3")
        assert tasks_mod._collect_task["status"] == "failed"

    def test_例外はfailedのまま(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _boom():
            raise RuntimeError("scrape died")

        monkeypatch.setattr(tasks_mod, "collect_all_once", _boom)
        tasks_mod._run_collect_background("t4")
        assert tasks_mod._collect_task["status"] == "failed"
        assert "scrape died" in tasks_mod._collect_task["error"]


class Test同期モードのレスポンス:
    def test_全店成功ならok_true_200(self, client, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            tasks_mod, "collect_all_once",
            lambda: {"stores": 42, "success": 42, "fail": 0, "duration_sec": 8.1},
        )
        resp = client.get("/tasks/multi_collect?mode=sync")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["status"] == "completed"
        # 既存キーは不変（cron / 手動確認が読んでいる）
        assert body["task"] == "collect_all_once"
        assert (body["stores"], body["success"], body["fail"]) == (42, 42, 0)

    def test_一部失敗はok_falseだがHTTPは200のまま(self, client, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            tasks_mod, "collect_all_once", lambda: {"stores": 42, "success": 22, "fail": 20}
        )
        resp = client.get("/tasks/multi_collect?mode=sync")
        assert resp.status_code == 200  # cron-job.org の再試行挙動を変えない
        body = resp.get_json()
        assert body["ok"] is False
        assert body["status"] == "completed_with_failures"
        assert body["fail"] == 20

    def test_例外時もHTTPは200のままでok_false(self, client, monkeypatch: pytest.MonkeyPatch) -> None:
        def _boom():
            raise RuntimeError("nope")

        monkeypatch.setattr(tasks_mod, "collect_all_once", _boom)
        resp = client.get("/tasks/multi_collect?mode=sync")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is False and body["status"] == "failed"


class Testステータス照会:
    def test_last_runに直前の実行が残る(self, client, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            tasks_mod, "collect_all_once", lambda: {"stores": 42, "success": 22, "fail": 20}
        )
        tasks_mod._collect_task.update(task_id="t9", started_at="2026-08-21T09:00:00+00:00")
        tasks_mod._run_collect_background("t9")

        body = client.get("/tasks/multi_collect/status").get_json()
        assert body["ok"] is True
        assert body["status"] == "completed_with_failures"
        assert body["last_run"]["status"] == "completed_with_failures"
        assert body["last_run"]["result"]["fail"] == 20
        assert body["last_run"]["completed_at"]
        assert body["process_started_at"]

    def test_一度も走っていなければlast_runは空(self, client) -> None:
        body = client.get("/tasks/multi_collect/status").get_json()
        assert body["status"] == "idle"
        assert body["last_run"]["status"] is None
