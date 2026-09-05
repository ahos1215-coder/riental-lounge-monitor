"""日次公開チェックの「対象日」がGHAの遅延に耐えることを固定する（2026-09-06）。

背景:
  scripts/monitor/check_daily_published.py は cron `30 14 * * *` UTC（= 23:30 JST）で走り、
  「その日のJST日付」の日次レポートが42店揃っているかを見る。旧実装は対象日を
  `datetime.now(timezone.utc)` の **UTC日付** で決めていた。UTC日付は 00:00 UTC
  （= 09:00 JST）で変わるため、許容できる遅延が 9時間30分しか無かった。
  2026-08-27 に実測で 9時間23分の遅延が発生しており、あと7分で対象日が翌日へずれて
  「まだ生成されていない翌日分」を 0/42 と誤検知するところだった。

  そこで対象日を「JSTの現在時刻から18時間引いた日付」に変更し、許容遅延を
  18.5時間へ広げた。このテストは定刻・9時間遅延・18時間遅延・19時間遅延の4点で
  その境界を固定する（19時間は"ここから先は翌日を見る"という設計上の限界の明示）。

Supabase へは一切アクセスしない（HTTP は差し替える）。
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

MONITOR_DIR = Path(__file__).resolve().parents[1] / "scripts" / "monitor"
JST = timezone(timedelta(hours=9))


def _load(name: str):
    """scripts/monitor/<name>.py を単体モジュールとして読み込む（実行時と同じ形）。

    sys.modules のキーはこのファイル専用の接頭辞にする
    （tests/test_monitor_published_checks.py が同じファイルを別名で読むため、
      どちらが先に走っても互いの状態を壊さない）。
    """
    spec = importlib.util.spec_from_file_location(f"_monitor_date_{name}", MONITOR_DIR / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


daily = _load("check_daily_published")
weekly = _load("check_weekly_published")

# 定刻の発火時刻（JST）。2026-08-27 の実測遅延の再現に合わせてこの日を基準にする。
ON_TIME_JST = datetime(2026, 8, 27, 23, 30, tzinfo=JST)


def _target_after(delay_hours: float) -> str:
    """定刻から delay_hours だけ遅れて走ったときの対象日。"""
    return daily.resolve_target_date(ON_TIME_JST + timedelta(hours=delay_hours))


class Test対象日はGHA遅延に耐える:
    def test_定刻なら当日を見る(self) -> None:
        assert _target_after(0) == "2026-08-27"

    def test_9時間遅延でも当日を見る(self) -> None:
        """旧実装（UTC日付）が壊れ始める 9.5 時間の手前。実測は 9時間23分だった。"""
        assert _target_after(9) == "2026-08-27"

    def test_18時間遅延でも当日を見る(self) -> None:
        """新しいマージンの設計値。翌 17:30 JST まで当日を見る。"""
        assert _target_after(18) == "2026-08-27"

    def test_19時間遅延では翌日へ切り替わる(self) -> None:
        """設計上の限界（境界は翌 18:00 JST）。ここから先は翌日を対象にする。"""
        assert _target_after(19) == "2026-08-28"

    def test_境界は18時間30分ちょうど(self) -> None:
        assert _target_after(18.49) == "2026-08-27"
        assert _target_after(18.5) == "2026-08-28"

    def test_旧実装が誤検知していた9時間30分の遅延を救う(self) -> None:
        """回帰の芯: 旧実装（UTCの日付）はここで翌日へ飛び 0/42 の誤報を出していた。"""
        late = ON_TIME_JST + timedelta(hours=9, minutes=30)
        assert late.astimezone(timezone.utc).strftime("%Y-%m-%d") == "2026-08-28"  # 旧実装の出力
        assert daily.resolve_target_date(late) == "2026-08-27"  # 新実装

    def test_UTCで渡しても同じ日付になる(self) -> None:
        """main() は UTC の now を渡す。tz さえ付いていれば結果は変わらない。"""
        utc_now = ON_TIME_JST.astimezone(timezone.utc)
        assert daily.resolve_target_date(utc_now) == daily.resolve_target_date(ON_TIME_JST)

    def test_翌朝の手動実行は前夜を見る(self) -> None:
        """workflow_dispatch を翌朝 09:00 JST に打つと前日（= 確認したい夜）を見る。"""
        assert daily.resolve_target_date(datetime(2026, 8, 28, 9, 0, tzinfo=JST)) == "2026-08-27"


class Test対象日の決まり方:
    """main() 経由で INPUT_DATE の優先と自動決定の両方を固定する。"""

    def _run_main(self, monkeypatch: pytest.MonkeyPatch) -> list[str]:
        seen: list[str] = []

        def fake_fetch(url: str, key: str, target: str, edition: str) -> set[str]:
            seen.append(target)
            return set(daily.expected_slugs())

        monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
        monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "dummy-key-for-test")
        monkeypatch.delenv("ALLOWED_MISSING_SLUGS", raising=False)
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
        monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
        monkeypatch.setattr(daily, "fetch_published_slugs", fake_fetch)
        assert daily.main() == 0
        return seen

    def test_INPUT_DATEが明示されていればそれを使う(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("INPUT_DATE", "2026-07-04")
        assert self._run_main(monkeypatch) == ["2026-07-04", "2026-07-04"]

    def test_INPUT_DATE空欄なら18時間マージンで決める(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("INPUT_DATE", "  ")  # WF は未入力時に空文字を渡す

        class _FrozenDatetime(daily.datetime):  # type: ignore[misc, name-defined]
            @classmethod
            def now(cls, tz=None):  # noqa: ANN001, ANN206
                return ON_TIME_JST.astimezone(tz or timezone.utc)

        monkeypatch.setattr(daily, "datetime", _FrozenDatetime)
        assert self._run_main(monkeypatch) == ["2026-08-27", "2026-08-27"]


class Test週次には同じ日付境界の穴が無い:
    """週次側を確認した結果の記録（2026-09-06）。

    check_weekly_published.py は「対象日」を持たず、`now - updated_at` の相対年齢だけを
    MAX_STALENESS_DAYS と比べる。したがって遅延しても判定は連続的にしか変わらず、
    日付を跨いだ瞬間に対象がずれる、という日次側の穴は存在しない。
    つまり日次に入れた「JST -18時間」のマージンは週次には不要。ここではそれを
    「18時間遅れても判定が変わらない」という形で固定する。
    """

    FLEET = [f"s{i}" for i in range(42)]
    NOW = datetime(2026, 8, 27, 23, 0, tzinfo=timezone.utc)

    def _rows(self, updated_at: str) -> list[dict]:
        return [{"store_slug": s, "updated_at": updated_at} for s in self.FLEET]

    def test_18時間遅れても判定は変わらない(self) -> None:
        rows = self._rows("2026-08-26T21:30:00Z")  # 前日の週次生成
        for delay in (0, 9, 18, 19):
            _detail, problems = weekly.build_detail(
                rows,
                min_stores=38,
                max_staleness_days=8,
                now=self.NOW + timedelta(hours=delay),
                expected=self.FLEET,
            )
            assert problems == [], f"{delay}時間遅延で判定が変わった: {problems}"

    def test_週次には対象日を決める関数が無い(self) -> None:
        """日次の resolve_target_date に相当するものを週次へ足していないことの確認。"""
        assert not hasattr(weekly, "resolve_target_date")
