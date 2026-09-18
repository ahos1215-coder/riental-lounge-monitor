"""一時停止ゲート（scripts/monitor/quota_pause.py）の単体テスト。

このゲートは「監視をわざと黙らせる」仕掛けなので、壊れ方が静かで怖い。守るべき性質は5つ:

  1. **一次信号は黙らせない**… 抑えるのは「上流が死んでいれば必ず巻き添えで赤くなる」
     反響9本だけ。site-down-watch / check-collection-heartbeat にはゲート自体を付けない。
     ここが崩れると「全部緑なのに全部死んでいる」を自分で作り込むことになる
     （2026-09-18 時点では LINE が1本も届かず、GitHub の失敗メールが唯一の通知経路）。
  2. **戻り忘れが起きない**  … 反響側は状態を持たず、毎回その場で上流を観測して決める。
     上流が戻れば次の実行から自動で鳴る。日付モードは解除日を過ぎたら必ず通常運転で、
     既定の解除日そのものも番犬で固定する（誰かが不用意に延ばしたら赤くなる）。
  3. **天井がある**          … 日付モードの解除日はリポジトリ変数で延ばせるが、既定日＋30日を
     超える指定は採用しない。いちばん怖い「止めたまま戻し忘れ」を、コードの外の変数1つに
     丸ごと逃がさないための番犬（上限日数もここで固定する）。
  4. **手動実行は止めない**  … workflow_dispatch は Supabase を叩くまでもなく通常運転。
     手で回したのに何も起きず緑で終わる（＝動いたと誤解する）のを防ぐ。
  5. **fail-closed**        … 「上流が止まっている署名」を実際に観測したとき**だけ**止める。
     署名は HTTP 402 と Supabase ホストの名前解決失敗の2つだけ。それ以外
     （200/401/403/404/5xx・タイムアウト・接続拒否・例外・認証情報なし・日付が読めない）は
     全部 paused=false。「判定できなかったから止める」は 2026-09-05 の事故の再演になる。

Supabase へは一切アクセスしない（probe は差し替え。叩かないはずの経路では
"叩いたら失敗する probe" を渡して、通信していないこと自体をテストする）。
"""

from __future__ import annotations

import importlib.util
import socket
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

MONITOR_DIR = Path(__file__).resolve().parents[1] / "scripts" / "monitor"
WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"


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


class TestQUOTA_GATE_ALWAYSの読み方:
    """反響側のワークフローだけが渡すスイッチ。打ち間違いが「黙る側」に倒れないこと。"""

    def test_環境変数名は固定(self) -> None:
        assert qp.QUOTA_GATE_ALWAYS_ENV == "QUOTA_GATE_ALWAYS"

    @pytest.mark.parametrize("raw", ["1", "true", "TRUE", " yes ", "on", "On"])
    def test_肯定の値なら有効(self, raw: str) -> None:
        assert qp.always_enabled(raw) is True

    @pytest.mark.parametrize("raw", ["", "   ", "0", "false", "no", "off", "２", "yolo"])
    def test_それ以外は無効(self, raw: str) -> None:
        """ここが True 側に倒れると、変数の打ち間違いだけで監視が黙る。"""
        assert qp.always_enabled(raw) is False

    @pytest.mark.parametrize("raw", [None, 1, True])
    def test_文字列でなければ無効(self, raw: object) -> None:
        assert qp.always_enabled(raw) is False


class Test反響側は解除日を無視して抑える:
    """QUOTA_GATE_ALWAYS=1（反響9本）の挙動。

    守っている事故（2026-09-12〜09-16）: 9/11 に入れた日付ゲートは2日しか効かなかった。
    解除日 2026-09-16 を過ぎた後も上流はまだ死んでいて、反響9本が毎日メールを出し続けた。
    反響側は「日付」ではなく「上流が今どうか」で決めるのが正しい。
    """

    PAST = date(2026, 12, 25)  # 既定解除日も天井（2026-10-16）もとっくに過ぎている日

    def test_402なら解除日を過ぎていても抑える(self) -> None:
        paused, lines = qp.evaluate(
            until_raw=UNTIL,
            today=self.PAST,
            has_credentials=True,
            probe=_status_probe(402),
            always=True,
        )
        assert paused is True
        assert "反響を抑制中" in "\n".join(lines)

    def test_名前解決の失敗でも抑える(self) -> None:
        """9/12 以降の壊れ方。402 しか見ていなかったので素通りしていた。"""
        paused, lines = qp.evaluate(
            until_raw=UNTIL,
            today=self.PAST,
            has_credentials=True,
            probe=_status_probe(qp.DNS_FAILURE),
            always=True,
        )
        assert paused is True
        assert "ホスト名を解決できません" in "\n".join(lines)

    def test_天井を超える解除日が入っていても抑える(self) -> None:
        """always モードは日付を一切見ない（天井も解除日も無関係）。"""
        paused, _lines = qp.evaluate(
            until_raw="2027-01-01",
            today=self.PAST,
            has_credentials=True,
            probe=_status_probe(402),
            always=True,
        )
        assert paused is True

    def test_解除日が読めなくても抑える(self) -> None:
        paused, _lines = qp.evaluate(
            until_raw="こわれた日付",
            today=self.PAST,
            has_credentials=True,
            probe=_status_probe(402),
            always=True,
        )
        assert paused is True

    @pytest.mark.parametrize("status", [200, 401, 403, 404, 429, 500, 502, 503])
    def test_署名以外のステータスでは抑えない(self, status: int) -> None:
        """401/403 は本物の異常（キー失効・権限）。ここを黙らせると原因が見えなくなる。"""
        paused, lines = qp.evaluate(
            until_raw=UNTIL,
            today=self.PAST,
            has_credentials=True,
            probe=_status_probe(status),
            always=True,
        )
        assert paused is False
        assert str(status) in "\n".join(lines)

    def test_タイムアウトや接続拒否では抑えない(self) -> None:
        """probe が「判定不能（None）」を返す形。ランナー側の一時不調と区別できない。"""
        paused, lines = qp.evaluate(
            until_raw=UNTIL,
            today=self.PAST,
            has_credentials=True,
            probe=_status_probe(None),
            always=True,
        )
        assert paused is False
        assert "到達できませんでした" in "\n".join(lines)

    def test_probeが例外を投げても抑えない(self) -> None:
        def boom() -> int | None:
            raise RuntimeError("boom")

        paused, lines = qp.evaluate(
            until_raw=UNTIL,
            today=self.PAST,
            has_credentials=True,
            probe=boom,
            always=True,
        )
        assert paused is False
        assert "RuntimeError" in "\n".join(lines)

    def test_認証情報が無ければ叩かずに抑えない(self) -> None:
        paused, lines = qp.evaluate(
            until_raw=UNTIL,
            today=self.PAST,
            has_credentials=False,
            probe=_forbidden_probe(),
            always=True,
        )
        assert paused is False
        assert "認証情報" in "\n".join(lines)

    def test_手動実行は抑えない(self) -> None:
        """always モードでも workflow_dispatch は最優先で素通しさせる。"""
        probe = _unused_probe()
        paused, lines = qp.evaluate(
            until_raw=UNTIL,
            today=self.PAST,
            has_credentials=True,
            probe=probe,
            event_name="workflow_dispatch",
            always=True,
        )
        assert paused is False
        assert probe.calls == []
        assert "手動実行" in "\n".join(lines)

    def test_抑制中でも一次信号が動いていることを人に伝える(self) -> None:
        """「黙っている」と「全部黙っている」を読み違えさせないための一文。"""
        _paused, lines = qp.evaluate(
            until_raw=UNTIL,
            today=self.PAST,
            has_credentials=True,
            probe=_status_probe(402),
            always=True,
        )
        body = "\n".join(lines)
        assert "site-down-watch" in body
        assert "check-collection-heartbeat" in body

    def test_alwaysが無ければ解除日後は従来どおり抑えない(self) -> None:
        """既定（一次信号以外の未対応ジョブ・ローカル実行）が変わっていないこと。"""
        paused, _lines = qp.evaluate(
            until_raw=UNTIL,
            today=self.PAST,
            has_credentials=True,
            probe=_forbidden_probe(),  # 日付で先に抜けるので叩かない
        )
        assert paused is False


class Test止める署名は2つだけ:
    def test_402と名前解決失敗だけが署名(self) -> None:
        assert qp.is_down_signature(402) is True
        assert qp.is_down_signature(qp.DNS_FAILURE) is True

    @pytest.mark.parametrize("status", [None, 200, 401, 403, 404, 429, 500, 502, 503])
    def test_それ以外は署名ではない(self, status: int | None) -> None:
        assert qp.is_down_signature(status) is False


class Test名前解決の失敗を通信失敗と区別する:
    """probe_status の分類。ここが潰れると 9/12〜9/16 の再演になる。

    urllib は「名前が引けない」も「繋がらない」も「遅い」も全部 URLError で包む。
    区別できるのは reason の**型**だけなので、そこを見ていることを固定する。
    """

    @pytest.fixture(autouse=True)
    def _stub_auth(self, monkeypatch: pytest.MonkeyPatch):
        # 共通ヘルパ（scripts/_supabase_common.py）に依存せず probe_status 単体を見る。
        monkeypatch.setattr(qp, "_auth_headers", lambda _key: {})
        yield

    def _probe(self, monkeypatch: pytest.MonkeyPatch, raiser):
        def fake_urlopen(*_a, **_k):
            raise raiser()

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        return qp.probe_status("https://example.invalid", "dummy-key-not-a-secret")

    def test_名前解決の失敗は署名として返る(self, monkeypatch: pytest.MonkeyPatch) -> None:
        got = self._probe(
            monkeypatch,
            lambda: URLError(socket.gaierror(-2, "Name or service not known")),
        )
        assert got == qp.DNS_FAILURE
        assert qp.is_down_signature(got) is True

    def test_タイムアウトは判定不能(self, monkeypatch: pytest.MonkeyPatch) -> None:
        got = self._probe(monkeypatch, lambda: URLError("The read operation timed out"))
        assert got is None

    def test_接続拒否も判定不能(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """名前は引けている＝宛先は在る。上流が消えた証拠にはならない。"""
        got = self._probe(monkeypatch, lambda: URLError(ConnectionRefusedError(111, "refused")))
        assert got is None

    @pytest.mark.parametrize("code", [402, 401, 500])
    def test_HTTPErrorはステータスとして返る(
        self, monkeypatch: pytest.MonkeyPatch, code: int
    ) -> None:
        """HTTPError は URLError の子。捕まえる順番を間違えると 402 が消える。"""
        got = self._probe(
            monkeypatch,
            lambda: HTTPError(
                url="https://example.invalid/rest/v1/logs",
                code=code,
                msg="x",
                hdrs=None,  # type: ignore[arg-type]
                fp=None,
            ),
        )
        assert got == code

    def test_成功時はステータスを返す(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class _Resp:
            status = 200

            def __enter__(self):  # noqa: ANN204
                return self

            def __exit__(self, *_exc) -> bool:  # noqa: ANN002
                return False

        monkeypatch.setattr(urllib.request, "urlopen", lambda *_a, **_k: _Resp())
        assert qp.probe_status("https://example.invalid", "dummy-key-not-a-secret") == 200


class Test出力:
    def _run_main(self, monkeypatch, tmp_path, *, env: dict[str, str], status: int | str | None):
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
            "QUOTA_GATE_ALWAYS",
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

    def test_反響側のenvなら解除日後でもpaused_true(self, monkeypatch, tmp_path) -> None:
        """ワークフローが渡す QUOTA_GATE_ALWAYS が main まで届いていることの検問。"""
        monkeypatch.setattr(qp, "today_jst", lambda *a, **k: date(2026, 12, 25))
        code, out, summary = self._run_main(
            monkeypatch,
            tmp_path,
            env={
                "QUOTA_GATE_ALWAYS": "1",
                "SUPABASE_URL": "https://secretprojectref.supabase.co",
                "SUPABASE_SERVICE_ROLE_KEY": "service-role-key-value",
            },
            status=402,
        )
        assert code == 0
        assert "paused=true\n" in out
        assert "反響を抑制中" in summary
        assert "site-down-watch" in summary  # 一次信号が生きていることを人に見せる

    def test_反響側のenvで名前解決失敗でもpaused_true(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setattr(qp, "today_jst", lambda *a, **k: date(2026, 12, 25))
        code, out, summary = self._run_main(
            monkeypatch,
            tmp_path,
            env={
                "QUOTA_GATE_ALWAYS": "1",
                "SUPABASE_URL": "https://secretprojectref.supabase.co",
                "SUPABASE_SERVICE_ROLE_KEY": "service-role-key-value",
            },
            status=qp.DNS_FAILURE,
        )
        assert code == 0
        assert "paused=true\n" in out
        assert "ホスト名を解決できません" in summary

    def test_反響側のenvが無ければ解除日後はpaused_false(self, monkeypatch, tmp_path) -> None:
        """一次信号2本と同じ条件（ゲート自体が無い）へ落ちること。"""
        monkeypatch.setattr(qp, "today_jst", lambda *a, **k: date(2026, 12, 25))
        code, out, _summary = self._run_main(
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

    def test_反響側でも手動実行はpaused_false(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setattr(qp, "today_jst", lambda *a, **k: date(2026, 12, 25))
        code, out, summary = self._run_main(
            monkeypatch,
            tmp_path,
            env={
                "QUOTA_GATE_ALWAYS": "1",
                "GITHUB_EVENT_NAME": "workflow_dispatch",
                "SUPABASE_URL": "https://secretprojectref.supabase.co",
                "SUPABASE_SERVICE_ROLE_KEY": "service-role-key-value",
            },
            status=402,
        )
        assert code == 0
        assert "paused=false\n" in out
        assert "手動実行" in summary

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


# ── ワークフロー側の形の検問 ────────────────────────────────────────────────────
# 「1つの原因で11本がメールを出す」を「2本だけ」にする設計は、コードではなく
# **どのワークフローにゲートを置いたか**で決まる。そこは人が1本ずつ手で書くので、
# 付け忘れ・付けすぎが起きても誰も気づけない。ここで機械的に固定する。

GATE_STEP_ID = "quota_gate"
GATE_GUARD = "steps.quota_gate.outputs.paused != 'true'"

# 一次信号: 止まったこと自体を知らせる役。**ゲートを付けてはいけない**。
PRIMARY_SIGNALS = ("site-down-watch.yml", "check-collection-heartbeat.yml")

# 反響: 上流が死んでいれば必ず巻き添えで赤くなる側。ゲートを付ける。
# cleanup-old-logs.yml だけは2ジョブ（バックアップ確認と削除）にそれぞれ必要。
ECHOES = (
    "backup-logs.yml",
    "build-templates.yml",
    "check-blend-weights-freeze.yml",
    "check-daily-published.yml",
    "check-weekly-published.yml",
    "cleanup-old-logs.yml",
    "forecast-accuracy-track.yml",
    "train-ml-model.yml",
    "warm-cdn.yml",
)


def _load_yaml(name: str) -> dict:
    import yaml

    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def _jobs_with_steps(doc: dict) -> list[tuple[str, list[dict]]]:
    out: list[tuple[str, list[dict]]] = []
    for job_name, job in (doc.get("jobs") or {}).items():
        steps = (job or {}).get("steps")
        if isinstance(steps, list):
            out.append((job_name, steps))
    return out


class Test一次信号にはゲートを付けない:
    """ここが赤くなったら、止まったことを知らせる唯一の経路を自分で黙らせている。

    2026-09-11 にこの2本にもゲートを付けたが、09-18 に撤去した。理由は2つ:
      - 上流が死んでいる間こそ鳴らなければ、このワークフローの存在理由が消える。
      - 2026-09-18 時点で LINE は Secrets 未設定とトークン失効により1本も届いていない。
        GitHub の失敗メールが唯一の通知経路なので、ここを黙らせると本当に誰も気づけない。
    """

    @pytest.mark.parametrize("name", PRIMARY_SIGNALS)
    def test_ゲートのステップが無い(self, name: str) -> None:
        for job_name, steps in _jobs_with_steps(_load_yaml(name)):
            ids = [s.get("id") for s in steps]
            assert GATE_STEP_ID not in ids, f"{name} の jobs.{job_name} にゲートが復活している"

    @pytest.mark.parametrize("name", PRIMARY_SIGNALS)
    def test_ゲートのスクリプトを呼ばない(self, name: str) -> None:
        """見るのは YAML を解釈した結果＝**このWFが実際に何をするか**。

        生テキストを検索すると、冒頭コメントの「反響9本には QUOTA_GATE_ALWAYS が入って
        いる／こちらには付けない」という解説文にまで反応して赤くなる。説明を書いたことを
        後退と呼ばないために、run と env だけを見る。
        """
        for job_name, steps in _jobs_with_steps(_load_yaml(name)):
            for step in steps:
                assert "quota_pause.py" not in str(step.get("run") or ""), (
                    f"{name} jobs.{job_name} がゲートを実行している"
                )
                assert "QUOTA_GATE_ALWAYS" not in (step.get("env") or {}), (
                    f"{name} jobs.{job_name} に QUOTA_GATE_ALWAYS が渡っている"
                )

    @pytest.mark.parametrize("name", PRIMARY_SIGNALS)
    def test_pausedで条件分岐しているステップが無い(self, name: str) -> None:
        """ゲート本体を消しても `if:` の paused 条件が残っていれば、実質ずっと空文字で
        走り続ける。害は無いが「ゲートが在る」と読めてしまうので残さない。"""
        for job_name, steps in _jobs_with_steps(_load_yaml(name)):
            for step in steps:
                cond = str(step.get("if") or "")
                assert "quota_gate" not in cond, f"{name} jobs.{job_name}: {cond}"
                assert "paused" not in cond, f"{name} jobs.{job_name}: {cond}"


class Test反響にはQUOTA_GATE_ALWAYS付きのゲートがある:
    @pytest.mark.parametrize("name", ECHOES)
    def test_ゲートがありQUOTA_GATE_ALWAYSが1(self, name: str) -> None:
        found = 0
        for job_name, steps in _jobs_with_steps(_load_yaml(name)):
            gates = [s for s in steps if s.get("id") == GATE_STEP_ID]
            if not gates:
                continue
            assert len(gates) == 1, f"{name} jobs.{job_name} にゲートが複数ある"
            gate = gates[0]
            found += 1
            assert "quota_pause.py" in gate.get("run", ""), f"{name} jobs.{job_name}"
            env = gate.get("env") or {}
            assert env.get("QUOTA_GATE_ALWAYS") == "1", (
                f"{name} jobs.{job_name} に QUOTA_GATE_ALWAYS: \"1\" が無い"
                "（解除日 2026-09-16 を過ぎているので、無いと事実上ゲートが効かない）"
            )
            # 手動実行を素通しさせる材料と、署名判定に要る認証情報。
            assert env.get("GITHUB_EVENT_NAME") == "${{ github.event_name }}"
            assert "SUPABASE_URL" in env and "SUPABASE_SERVICE_ROLE_KEY" in env
        assert found >= 1, f"{name} にゲートを持つジョブが1つも無い"

    @pytest.mark.parametrize("name", ECHOES)
    def test_ゲート以降の全ステップにpaused条件がある(self, name: str) -> None:
        """1つでも条件の付いていないステップが残ると、そこで落ちてメールが出る
        ＝抑制したつもりで抑制できていない（しかも気づきにくい）。"""
        for job_name, steps in _jobs_with_steps(_load_yaml(name)):
            ids = [s.get("id") for s in steps]
            if GATE_STEP_ID not in ids:
                continue
            for step in steps[ids.index(GATE_STEP_ID) + 1 :]:
                cond = str(step.get("if") or "")
                assert GATE_GUARD in cond, (
                    f"{name} jobs.{job_name} の "
                    f"'{step.get('name') or step.get('id')}' に paused 条件が無い（if: {cond!r}）"
                )

    def test_ゲートを持つジョブは10個(self) -> None:
        """9本・10ジョブ（cleanup-old-logs だけ2ジョブ）。増減したら設計の変更なので気づく。"""
        gated: list[str] = []
        for path in sorted(WORKFLOWS.glob("*.yml")):
            for job_name, steps in _jobs_with_steps(_load_yaml(path.name)):
                if any(s.get("id") == GATE_STEP_ID for s in steps):
                    gated.append(f"{path.name}:{job_name}")
        assert len(gated) == 10, f"ゲートを持つジョブ: {gated}"
        # 一次信号が紛れ込んでいないことも同時に見る
        assert not [g for g in gated if g.split(":")[0] in PRIMARY_SIGNALS]
