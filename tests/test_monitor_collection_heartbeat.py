"""収集ハートビート監視（scripts/monitor/check_collection_heartbeat.py）の単体テスト（B-10）。

もとは .github/workflows/check-collection-heartbeat.yml の YAML ヒアドキュメントに
直書きされていて、過去2度の誤報修正（昼間の一律30分閾値・夜窓開始のグレースピリオド）が
テストで守られていなかった。移設にあたり、その2件の再発防止を含めて固定する。

Supabase へは一切アクセスしない（判定は純関数、店舗別照会は差し替え）。
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
    spec = importlib.util.spec_from_file_location(f"_monitor_{name}", MONITOR_DIR / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


hb = _load("check_collection_heartbeat")


def _utc(y: int, mo: int, d: int, h: int, mi: int = 0, s: int = 0) -> datetime:
    """JST 指定で作って UTC に直す（本番の now は UTC で渡る）。"""
    return datetime(y, mo, d, h, mi, s, tzinfo=JST).astimezone(timezone.utc)


class Test夜窓開始のグレースピリオド:
    """2026-07-15 19:01:57 の「846分停止」誤報（夜窓の1行目は19:03頃に届く）の再発防止。"""

    def test_19時01分は前夜からの経過が長くてもOK(self) -> None:
        now = _utc(2026, 8, 19, 19, 1, 57)
        newest = _utc(2026, 8, 19, 4, 55)  # 前夜の最終行（約846分前）
        mode, ok, _fail, age = hb.evaluate_overall(newest, now, 30, "x")
        assert ok is True
        assert "夜間窓" in mode
        assert age > 800

    def test_19時04分もまだグレースピリオド内(self) -> None:
        now = _utc(2026, 8, 19, 19, 4, 30)
        newest = _utc(2026, 8, 19, 4, 55)
        _mode, ok, _fail, _age = hb.evaluate_overall(newest, now, 30, "x")
        assert ok is True

    def test_19時31分に1行も来ていなければNG(self) -> None:
        """グレース(=閾値30分)を過ぎたら従来どおりの陳腐化判定に戻る。"""
        now = _utc(2026, 8, 19, 19, 31)
        newest = _utc(2026, 8, 19, 4, 55)
        _mode, ok, fail, _age = hb.evaluate_overall(newest, now, 30, "x")
        assert ok is False
        assert "分間停止しています" in fail

    def test_夜間に収集が生きていればOK(self) -> None:
        now = _utc(2026, 8, 19, 22, 0)
        newest = _utc(2026, 8, 19, 21, 55)
        _mode, ok, _fail, age = hb.evaluate_overall(newest, now, 30, "x")
        assert ok is True
        assert age == pytest.approx(5.0)


class Test日付跨ぎの夜窓:
    def test_深夜2時の夜窓開始は前日の19時(self) -> None:
        now = _utc(2026, 8, 20, 2, 0)
        newest = _utc(2026, 8, 20, 1, 55)
        mode, ok, _fail, _age = hb.evaluate_overall(newest, now, 30, "x")
        assert ok is True
        # 前日19:00 起点なので 7 時間 = 420 分経過している
        assert "開始から420.0分" in mode

    def test_深夜2時に収集が止まっていればNG(self) -> None:
        now = _utc(2026, 8, 20, 2, 0)
        newest = _utc(2026, 8, 19, 23, 0)  # 3時間前
        _mode, ok, _fail, _age = hb.evaluate_overall(newest, now, 30, "x")
        assert ok is False


class Test昼間の完走チェック:
    def test_前夜が閉店間際まで走っていればOK(self) -> None:
        now = _utc(2026, 8, 19, 12, 0)
        newest = _utc(2026, 8, 19, 4, 55)  # 05:00 の 5 分前
        mode, ok, _fail, _age = hb.evaluate_overall(newest, now, 30, "x")
        assert ok is True
        assert mode == "昼間(前夜の完走チェック)"

    def test_昼間は経過が数百分でも誤報しない(self) -> None:
        """2026-07-08〜10 に毎日出ていた昼間の偽アラートの再発防止。"""
        now = _utc(2026, 8, 19, 18, 0)
        newest = _utc(2026, 8, 19, 4, 55)
        _mode, ok, _fail, age = hb.evaluate_overall(newest, now, 30, "x")
        assert ok is True
        assert age > 780

    def test_前夜が45分より前で止まっていればNG(self) -> None:
        now = _utc(2026, 8, 19, 12, 0)
        newest = _utc(2026, 8, 19, 4, 0)  # 05:00 の 60 分前
        _mode, ok, fail, _age = hb.evaluate_overall(newest, now, 30, "x")
        assert ok is False
        assert "営業終了の 60 分前で止まっています" in fail

    def test_ちょうど45分前は許容(self) -> None:
        now = _utc(2026, 8, 19, 12, 0)
        newest = _utc(2026, 8, 19, 4, 15)
        _mode, ok, _fail, _age = hb.evaluate_overall(newest, now, 30, "x")
        assert ok is True


class Test店舗別チェック:
    NOW = _utc(2026, 8, 19, 12, 0)

    def _patch_store_query(self, monkeypatch: pytest.MonkeyPatch, table: dict) -> None:
        def _fake(url, key, store_id):  # noqa: ANN001
            return table.get(store_id, (None, None))

        monkeypatch.setattr(hb, "newest_ts_for_store", _fake)

    def test_新鮮な店だけなら陳腐化ゼロ(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fresh = _utc(2026, 8, 19, 4, 55).isoformat()
        self._patch_store_query(monkeypatch, {"ol_a": (fresh, None), "ol_b": (fresh, None)})
        stale, errors, checked = hb.check_per_store(
            "u", "k",
            [{"store_id": "ol_a", "label": "A"}, {"store_id": "ol_b", "label": "B"}],
            self.NOW, 3.0,
        )
        assert (stale, errors, checked) == ([], [], 2)

    def test_古い店は店名付きで報告される(self, monkeypatch: pytest.MonkeyPatch) -> None:
        old = _utc(2026, 7, 1, 4, 55).isoformat()
        self._patch_store_query(monkeypatch, {"ol_dead": (old, None)})
        stale, _errors, checked = hb.check_per_store(
            "u", "k", [{"store_id": "ol_dead", "label": "閉店店舗"}], self.NOW, 3.0
        )
        assert checked == 1
        assert len(stale) == 1
        assert stale[0].startswith("ol_dead(閉店店舗): 最新 ")
        assert "(>3日)" in stale[0]

    def test_1行も無い店は収集行なしとして報告(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._patch_store_query(monkeypatch, {"ol_new": (None, None)})
        stale, _errors, _checked = hb.check_per_store(
            "u", "k", [{"store_id": "ol_new", "label": "新店"}], self.NOW, 3.0
        )
        assert stale == ["ol_new(新店): 収集行なし"]

    def test_照会失敗だけでは陳腐化にしない(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """一時的な通信エラーで監視ジョブを落とさない（誤検知回避）ための仕様。"""
        self._patch_store_query(monkeypatch, {"ol_x": (None, TimeoutError("boom"))})
        stale, errors, checked = hb.check_per_store(
            "u", "k", [{"store_id": "ol_x", "label": "X"}], self.NOW, 3.0
        )
        assert stale == []
        assert errors == ["ol_x(X)"]
        assert checked == 0

    def test_store_idが空の行は飛ばす(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._patch_store_query(monkeypatch, {})
        stale, errors, checked = hb.check_per_store(
            "u", "k", [{"store_id": "  ", "label": "空"}], self.NOW, 3.0
        )
        assert (stale, errors, checked) == ([], [], 0)


def test_Supabase未設定なら1で終わる(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    assert hb.main() == 1
    assert "::error::SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY secret 未設定" in capsys.readouterr().out
