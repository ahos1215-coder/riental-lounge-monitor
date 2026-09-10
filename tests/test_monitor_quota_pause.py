"""一時停止ゲート（scripts/monitor/quota_pause.py）の単体テスト。

このゲートは「監視をわざと黙らせる」仕掛けなので、壊れ方が静かで怖い。守るべき性質は4つ:

  1. **戻り忘れが起きない**  … 解除日を過ぎたら、Supabase の状態を見るまでもなく通常運転。
     既定の解除日そのものも番犬で固定する（誰かが不用意に延ばしたら赤くなる）。
  2. **天井がある**          … 解除日はリポジトリ変数で延ばせるが、既定日＋30日を超える
     指定は採用しない。いちばん怖い「止めたまま戻し忘れ」を、コードの外の変数1つに
     丸ごと逃がさないための番犬（上限日数もここで固定する）。
  3. **手動実行は止めない**  … workflow_dispatch は Supabase を叩くまでもなく通常運転。
     手で回したのに何も起きず緑で終わる（＝動いたと誤解する）のを防ぐ。
  4. **fail-closed**        … 402 を実際に観測したとき**だけ**止める。それ以外
     （200/401/403/404/5xx・タイムアウト・例外・認証情報なし・日付が読めない）は全部
     paused=false。「判定できなかったから止める」は 2026-09-05 の事故の再演になる。

Supabase へは一切アクセスしない（probe は差し替え。叩かないはずの経路では
"叩いたら失敗する probe" を渡して、通信していないこと自体をテストする）。
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

MONITOR_DIR = Path(__file__).resolve().parents[1] / "scripts" / "monitor"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"_monitor_{name}", MONITOR_DIR / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


qp = _load("quota_pause")

UNTIL = "2026-09-16"


def _forbidden_probe():
    """呼ばれたらテストを落とす probe（＝ここでは Supabase を叩いてはいけない）。"""

    def probe() -> int | None:
        raise AssertionError("この経路では Supabase を叩いてはいけない")

    return probe


def _status_probe(status: int | None):
    calls: list[int] = []

    def probe() -> int | None:
        calls.append(1)
        return status

    probe.calls = calls  # type: ignore[attr-defined]
    return probe


def _unused_probe():
    """「叩かないはず」の経路用。402 を返す＋呼ばれた回数を数える。

    _forbidden_probe（例外を投げる）だけでは足りない: evaluate は probe の例外を
    握りつぶして paused=false にするので、「分岐が消えて probe が呼ばれた」ケースでも
    paused=false のままになり、テストが素通りしてしまう。402 を返すようにしておけば、
    分岐が消えた瞬間 paused=true になって必ず落ちる。calls で呼ばれていないことも見る。
    """
    return _status_probe(402)


class Test既定の解除日:
    """定数の番犬。延長は「リポジトリ変数で」が設計で、コード側の既定を静かに伸ばさせない。"""

    def test_既定は2026_09_16(self) -> None:
        assert qp.DEFAULT_PAUSE_UNTIL == "2026-09-16"

    def test_止めるステータスは402だけ(self) -> None:
        assert qp.PAUSE_STATUS == 402


class Test解除日の天井:
    """リポジトリ変数で延ばせる幅の上限。ここが緩むと「恒久的に黙る」が変数1つで起きる。"""

    def test_上限日数は30日で固定(self) -> None:
        assert qp.MAX_PAUSE_EXTENSION_DAYS == 30

    def test_天井は既定日から数える(self) -> None:
        assert qp.ceiling_until() == date(2026, 10, 16)  # 2026-09-16 + 30日

    def test_上限の内側なら採用して止める(self) -> None:
        """変数での延長そのものは殺さない（運用上の逃がし弁は残す）。"""
        paused, _lines = qp.evaluate(
            until_raw="2026-10-01",
            today=date(2026, 9, 11),
            has_credentials=True,
            probe=_status_probe(402),
        )
        assert paused is True

    def test_境界ちょうどは採用して止める(self) -> None:
        paused, lines = qp.evaluate(
            until_raw="2026-10-16",
            today=date(2026, 9, 11),
            has_credentials=True,
            probe=_status_probe(402),
        )
        assert paused is True
        assert "2026-10-16" in "\n".join(lines)

    def test_境界の翌日は叩かずに通常運転(self) -> None:
        probe = _unused_probe()
        paused, lines = qp.evaluate(
            until_raw="2026-10-17",
            today=date(2026, 9, 11),
            has_credentials=True,
            probe=probe,
        )
        assert paused is False
        assert probe.calls == []  # 天井の外なら Supabase を見るまでもない
        body = "\n".join(lines)
        assert "上限を超えている" in body
        assert "2026-10-16" in body  # 上限そのものを人に見せる

    def test_遠い未来を入れても止まらない(self) -> None:
        """このテストが守っている事故: 誰かが 2027-01-01 を入れて11本が恒久的に黙る。"""
        probe = _unused_probe()
        paused, lines = qp.evaluate(
            until_raw="2027-01-01",
            today=date(2026, 9, 11),
            has_credentials=True,
            probe=probe,
        )
        assert paused is False
        assert probe.calls == []
        assert "上限を超えている" in "\n".join(lines)

    def test_既定日が壊れていれば天井を出せないので止めない(self, monkeypatch) -> None:
        monkeypatch.setattr(qp, "DEFAULT_PAUSE_UNTIL", "こわれた日付")
        assert qp.ceiling_until() is None
        probe = _unused_probe()
        paused, lines = qp.evaluate(
            until_raw="2026-09-17",
            today=date(2026, 9, 11),
            has_credentials=True,
            probe=probe,
        )
        assert paused is False
        assert probe.calls == []
        assert "上限を超えている" in "\n".join(lines)


class Test手動実行は止めない:
    """workflow_dispatch は人の意思。ゲートに食われて「緑だが何もしていない」を作らない。"""

    def test_定数はworkflow_dispatch(self) -> None:
        assert qp.MANUAL_EVENT_NAME == "workflow_dispatch"

    def test_手動実行なら叩かずに通常運転(self) -> None:
        probe = _unused_probe()  # 402 を返す。分岐が消えれば paused=true になって落ちる
        paused, lines = qp.evaluate(
            until_raw=UNTIL,
            today=date(2026, 9, 11),  # 期限前＝本来なら止まる条件
            has_credentials=True,
            probe=probe,
            event_name="workflow_dispatch",
        )
        assert paused is False
        assert probe.calls == []  # Supabase を叩くまでもなく抜けること
        assert "手動実行" in "\n".join(lines)

    def test_手動実行は解除日が読めなくても壊れない(self) -> None:
        """日付判定より前に抜けるので、変数がおかしくても手動実行は必ず走る。"""
        probe = _unused_probe()
        paused, lines = qp.evaluate(
            until_raw="こわれた日付",
            today=date(2026, 9, 11),
            has_credentials=True,
            probe=probe,
            event_name="workflow_dispatch",
        )
        assert paused is False
        assert probe.calls == []
        assert "手動実行" in "\n".join(lines)  # 「読めませんでした」ではなくこちらが出る

    def test_大文字混じりでも手動実行として扱う(self) -> None:
        probe = _unused_probe()
        paused, lines = qp.evaluate(
            until_raw=UNTIL,
            today=date(2026, 9, 11),
            has_credentials=True,
            probe=probe,
            event_name=" Workflow_Dispatch ",
        )
        assert paused is False
        assert probe.calls == []
        assert "手動実行" in "\n".join(lines)

    @pytest.mark.parametrize("event", ["schedule", "push", "repository_dispatch"])
    def test_自動起動は従来どおり止まる(self, event: str) -> None:
        paused, _lines = qp.evaluate(
            until_raw=UNTIL,
            today=date(2026, 9, 11),
            has_credentials=True,
            probe=_status_probe(402),
            event_name=event,
        )
        assert paused is True

    @pytest.mark.parametrize("event", ["", "   "])
    def test_未設定や空文字でも従来どおりの判定に落ちる(self, event: str) -> None:
        """ローカル実行や env 未対応のワークフローの挙動を変えないこと。"""
        paused, _lines = qp.evaluate(
            until_raw=UNTIL,
            today=date(2026, 9, 11),
            has_credentials=True,
            probe=_status_probe(402),
            event_name=event,
        )
        assert paused is True

    def test_引数を渡さなくても従来どおりの判定になる(self) -> None:
        paused, _lines = qp.evaluate(
            until_raw=UNTIL,
            today=date(2026, 9, 11),
            has_credentials=True,
            probe=_status_probe(402),
        )
        assert paused is True


class Test期限で必ず自動解除される:
    def test_期限当日は叩かずに通常運転(self) -> None:
        paused, lines = qp.evaluate(
            until_raw=UNTIL,
            today=date(2026, 9, 16),
            has_credentials=True,
            probe=_forbidden_probe(),
        )
        assert paused is False
        assert "通常運転" in lines[0]

    def test_期限翌日も叩かずに通常運転(self) -> None:
        paused, _lines = qp.evaluate(
            until_raw=UNTIL,
            today=date(2026, 9, 17),
            has_credentials=True,
            probe=_forbidden_probe(),
        )
        assert paused is False

    def test_ずっと先の未来でも通常運転(self) -> None:
        """「Supabase が直らないまま放置」で永久に黙る、が起きないことの確認。"""
        paused, _lines = qp.evaluate(
            until_raw=UNTIL,
            today=date(2027, 1, 1),
            has_credentials=True,
            probe=_forbidden_probe(),
        )
        assert paused is False


class Test止めるのは402のときだけ:
    def test_期限前かつ402なら一時停止(self) -> None:
        paused, lines = qp.evaluate(
            until_raw=UNTIL,
            today=date(2026, 9, 11),
            has_credentials=True,
            probe=_status_probe(402),
        )
        assert paused is True
        body = "\n".join(lines)
        assert "一時停止中" in body
        assert "2026-09-16" in body
        assert "残り 5 日" in body

    def test_期限の前日でも402なら一時停止(self) -> None:
        paused, lines = qp.evaluate(
            until_raw=UNTIL,
            today=date(2026, 9, 15),
            has_credentials=True,
            probe=_status_probe(402),
        )
        assert paused is True
        assert "残り 1 日" in "\n".join(lines)

    @pytest.mark.parametrize("status", [200, 401, 403, 404, 429, 500, 502, 503])
    def test_402以外はすべて通常運転(self, status: int) -> None:
        paused, lines = qp.evaluate(
            until_raw=UNTIL,
            today=date(2026, 9, 11),
            has_credentials=True,
            probe=_status_probe(status),
        )
        assert paused is False
        assert str(status) in "\n".join(lines)


class Test判定できないときは止めない:
    def test_タイムアウト等でステータスが取れなければ通常運転(self) -> None:
        paused, lines = qp.evaluate(
            until_raw=UNTIL,
            today=date(2026, 9, 11),
            has_credentials=True,
            probe=_status_probe(None),
        )
        assert paused is False
        assert "到達できませんでした" in "\n".join(lines)

    def test_probeが例外を投げても通常運転(self) -> None:
        def boom() -> int | None:
            raise RuntimeError("boom")

        paused, lines = qp.evaluate(
            until_raw=UNTIL,
            today=date(2026, 9, 11),
            has_credentials=True,
            probe=boom,
        )
        assert paused is False
        assert "RuntimeError" in "\n".join(lines)

    def test_認証情報が無ければ叩かずに通常運転(self) -> None:
        paused, lines = qp.evaluate(
            until_raw=UNTIL,
            today=date(2026, 9, 11),
            has_credentials=False,
            probe=_forbidden_probe(),
        )
        assert paused is False
        assert "認証情報" in "\n".join(lines)

    @pytest.mark.parametrize("bad", ["", "   ", "2026/09/16", "20260916", "soon", "2026-13-40", "9/16"])
    def test_解除日が読めなければ叩かずに通常運転(self, bad: str) -> None:
        paused, lines = qp.evaluate(
            until_raw=bad,
            today=date(2026, 9, 11),
            has_credentials=True,
            probe=_forbidden_probe(),
        )
        assert paused is False
        assert "読めませんでした" in "\n".join(lines)


class Test日付の解釈:
    def test_厳格にYYYY_MM_DDだけ受ける(self) -> None:
        assert qp.parse_until("2026-09-16") == date(2026, 9, 16)
        assert qp.parse_until("20260916") is None  # 3.11 の fromisoformat なら通ってしまう表記
        assert qp.parse_until(None) is None

    def test_今日はJSTで数える(self) -> None:
        """JST の日付境界は UTC 15:00。UTC で判定すると解除が丸1日ずれる。"""
        boundary = datetime(2026, 9, 15, 15, 0, tzinfo=timezone.utc)  # = JST 9/16 00:00
        assert qp.today_jst(boundary) == date(2026, 9, 16)
        assert qp.today_jst(boundary - timedelta(minutes=1)) == date(2026, 9, 15)


class Test出力:
    def _run_main(self, monkeypatch, tmp_path, *, env: dict[str, str], status: int | None):
        out = tmp_path / "gh_output"
        summary = tmp_path / "gh_summary"
        monkeypatch.setenv("GITHUB_OUTPUT", str(out))
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
        # GITHUB_EVENT_NAME も消す。CI（GHA）の上でテストを走らせると本物の値が
        # 入っていて、手動実行の分岐が意図せず効いてしまうため。
        for k in (
            "OPS_QUOTA_PAUSE_UNTIL",
            "SUPABASE_URL",
            "SUPABASE_SERVICE_ROLE_KEY",
            "GITHUB_EVENT_NAME",
        ):
            monkeypatch.delenv(k, raising=False)
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        monkeypatch.setattr(qp, "probe_status", lambda *a, **k: status)
        code = qp.main()
        return code, out.read_text(encoding="utf-8"), summary.read_text(encoding="utf-8")

    def test_402ならpaused_trueを書いて成功終了(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setattr(qp, "today_jst", lambda *a, **k: date(2026, 9, 11))
        code, out, summary = self._run_main(
            monkeypatch,
            tmp_path,
            env={
                "SUPABASE_URL": "https://secretprojectref.supabase.co",
                "SUPABASE_SERVICE_ROLE_KEY": "service-role-key-value",
            },
            status=402,
        )
        assert code == 0
        assert "paused=true\n" in out
        assert "一時停止中" in summary

    def test_期限後はpaused_falseを書いて成功終了(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setattr(qp, "today_jst", lambda *a, **k: date(2026, 9, 16))
        code, out, _summary = self._run_main(
            monkeypatch,
            tmp_path,
            env={
                "SUPABASE_URL": "https://secretprojectref.supabase.co",
                "SUPABASE_SERVICE_ROLE_KEY": "service-role-key-value",
            },
            status=402,  # 402 でも期限後なので止めない
        )
        assert code == 0
        assert "paused=false\n" in out

    def test_環境変数が空なら既定の解除日が使われる(self, monkeypatch, tmp_path) -> None:
        """vars.OPS_QUOTA_PAUSE_UNTIL 未設定の GHA では空文字が入る。既定へ落ちること。"""
        monkeypatch.setattr(qp, "today_jst", lambda *a, **k: date(2026, 9, 11))
        code, out, summary = self._run_main(
            monkeypatch,
            tmp_path,
            env={
                "OPS_QUOTA_PAUSE_UNTIL": "",
                "SUPABASE_URL": "https://secretprojectref.supabase.co",
                "SUPABASE_SERVICE_ROLE_KEY": "service-role-key-value",
            },
            status=402,
        )
        assert code == 0
        assert "paused=true\n" in out
        assert qp.DEFAULT_PAUSE_UNTIL in summary

    def test_手動実行のenvがあれば402でもpaused_false(self, monkeypatch, tmp_path) -> None:
        """ワークフローが渡す GITHUB_EVENT_NAME が main まで届いていることの検問。"""
        monkeypatch.setattr(qp, "today_jst", lambda *a, **k: date(2026, 9, 11))
        code, out, summary = self._run_main(
            monkeypatch,
            tmp_path,
            env={
                "GITHUB_EVENT_NAME": "workflow_dispatch",
                "SUPABASE_URL": "https://secretprojectref.supabase.co",
                "SUPABASE_SERVICE_ROLE_KEY": "service-role-key-value",
            },
            status=402,  # 402 でも手動実行なので止めない
        )
        assert code == 0
        assert "paused=false\n" in out
        assert "手動実行" in summary

    def test_scheduleのenvなら従来どおり止まる(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setattr(qp, "today_jst", lambda *a, **k: date(2026, 9, 11))
        code, out, _summary = self._run_main(
            monkeypatch,
            tmp_path,
            env={
                "GITHUB_EVENT_NAME": "schedule",
                "SUPABASE_URL": "https://secretprojectref.supabase.co",
                "SUPABASE_SERVICE_ROLE_KEY": "service-role-key-value",
            },
            status=402,
        )
        assert code == 0
        assert "paused=true\n" in out

    def test_上限を超える変数が入っていても止まらない(self, monkeypatch, tmp_path) -> None:
        """リポジトリ変数に遠い未来を入れて忘れる、が main 経路でも効かないこと。"""
        monkeypatch.setattr(qp, "today_jst", lambda *a, **k: date(2026, 9, 11))
        code, out, summary = self._run_main(
            monkeypatch,
            tmp_path,
            env={
                "OPS_QUOTA_PAUSE_UNTIL": "2027-01-01",
                "SUPABASE_URL": "https://secretprojectref.supabase.co",
                "SUPABASE_SERVICE_ROLE_KEY": "service-role-key-value",
            },
            status=402,
        )
        assert code == 0
        assert "paused=false\n" in out
        assert "上限を超えている" in summary

    def test_予期しない例外でもpaused_falseを書いて成功終了(self, monkeypatch, tmp_path) -> None:
        def boom(**kwargs):
            raise ValueError("想定外")

        monkeypatch.setattr(qp, "evaluate", boom)
        code, out, summary = self._run_main(
            monkeypatch,
            tmp_path,
            env={
                "SUPABASE_URL": "https://secretprojectref.supabase.co",
                "SUPABASE_SERVICE_ROLE_KEY": "service-role-key-value",
            },
            status=402,
        )
        assert code == 0
        assert "paused=false\n" in out
        assert "ValueError" in summary
        assert "想定外" not in summary  # 例外メッセージは公開ログに出さない

    def test_公開サマリにホスト名やキーを出さない(self, monkeypatch, tmp_path) -> None:
        """このリポジトリは PUBLIC。ステップサマリに出してよいのはステータスコードだけ。"""
        monkeypatch.setattr(qp, "today_jst", lambda *a, **k: date(2026, 9, 11))
        for status in (402, 200, None):
            _code, _out, summary = self._run_main(
                monkeypatch,
                tmp_path / f"s{status}",
                env={
                    "SUPABASE_URL": "https://secretprojectref.supabase.co",
                    "SUPABASE_SERVICE_ROLE_KEY": "service-role-key-value",
                },
                status=status,
            )
            for leaked in ("secretprojectref", "supabase.co", "service-role-key-value", "/rest/v1/"):
                assert leaked not in summary, f"status={status} で {leaked} が漏れている"

    def test_GITHUB_OUTPUTが無くても落ちない(self, monkeypatch, capsys) -> None:
        """GHA 外（ローカル実行）でも例外にせず標準出力だけ出す。"""
        monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
        qp.emit(False, ["通常運転: テスト"])
        assert "通常運転: テスト" in capsys.readouterr().out


@pytest.fixture(autouse=True)
def _tmp_subdir(tmp_path: Path):
    """test_公開サマリ... が tmp_path のサブディレクトリを使うため、先に作っておく。"""
    for status in (402, 200, None):
        (tmp_path / f"s{status}").mkdir(exist_ok=True)
    yield
