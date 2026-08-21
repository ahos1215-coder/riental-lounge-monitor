"""監視スクリプト（日次/週次レポートの公開チェック）の単体テスト（B-10 / F8）。

もとは .github/workflows/check-daily-published.yml / check-weekly-published.yml の
YAML ヒアドキュメントに直書きされていて、テストから触れなかったロジック。
scripts/monitor/ へ移した上で、閾値判定・サマリ文言・終了コードを固定する。

2026-08-21（外部レビュー F8）: 判定を「件数が閾値以上か」から「期待する店舗 slug 集合
との差分」へ変えた。旧実装では
  - 日次: 各便 30 件（既定）あれば緑 = 12 店が毎日失敗しても検知できない
  - 週次: distinct 38 店 かつ**全体の最新1件**が8日以内なら緑 = 41 店が何週も
          古くても、1 店だけ新しければ緑
という穴があった。ここではその穴が塞がったことを固定する。

Supabase へは一切アクセスしない（HTTP は差し替え or 引数で注入）。
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

MONITOR_DIR = Path(__file__).resolve().parents[1] / "scripts" / "monitor"


def _load(name: str):
    """scripts/monitor/<name>.py を単体モジュールとして読み込む（実行時と同じ形）。"""
    spec = importlib.util.spec_from_file_location(f"_monitor_{name}", MONITOR_DIR / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


daily = _load("check_daily_published")
weekly = _load("check_weekly_published")

FLEET = [f"s{i}" for i in range(42)]


class Test日次の店舗集合判定:
    def test_全店揃っていればOK(self) -> None:
        detail, missing = daily.build_detail(
            "2026-08-19", 30,
            {"evening_preview": set(FLEET), "late_update": set(FLEET)},
            FLEET,
        )
        assert missing == []
        assert "- evening_preview: 42/42 店 公開 OK" in detail
        assert "- late_update: 42/42 店 公開 OK" in detail

    def test_旧実装なら緑だった12店欠けを検知する(self) -> None:
        """F8 の中核: 30/42 でも「不足」にする（旧実装は floor=30 で緑だった）。"""
        published = set(FLEET[:30])
        detail, missing = daily.build_detail(
            "2026-08-19", 30, {"evening_preview": published, "late_update": set(FLEET)}, FLEET
        )
        assert missing and missing[0].startswith("evening_preview=30")
        assert "欠落 12 店" in detail
        assert "s30" in detail  # 欠けた店舗名が出る

    def test_1店だけ欠けても不足になる(self) -> None:
        published = set(FLEET) - {"s7"}
        _detail, missing = daily.build_detail(
            "2026-08-19", 30, {"evening_preview": published, "late_update": set(FLEET)}, FLEET
        )
        assert missing == ["evening_preview=41(欠落:s7)"]

    def test_STRICT_OFFなら旧挙動のフロア判定へ戻る(self) -> None:
        published = set(FLEET[:30])
        _detail, missing = daily.build_detail(
            "2026-08-19", 30,
            {"evening_preview": published, "late_update": set(FLEET)},
            FLEET,
            strict=False,
        )
        assert missing == []

    def test_期待外のslugは失敗にしないが表示する(self) -> None:
        published = set(FLEET) | {"sapporo_ag"}
        detail, missing = daily.build_detail(
            "2026-08-19", 30, {"evening_preview": published, "late_update": set(FLEET)}, FLEET
        )
        assert missing == []
        assert "期待外の slug: sapporo_ag" in detail

    def test_期待集合はALLOWED_MISSING_SLUGSで縮められる(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ALLOWED_MISSING_SLUGS", "shibuya, ay_ueno")
        got = daily.expected_slugs()
        assert "shibuya" not in got and "ay_ueno" not in got
        monkeypatch.delenv("ALLOWED_MISSING_SLUGS")
        assert "shibuya" in daily.expected_slugs()


def _row(slug: str, updated_at: str | None) -> dict:
    return {"store_slug": slug, "updated_at": updated_at}


class Test週次の店舗別鮮度判定:
    NOW = datetime(2026, 8, 20, 0, 0, tzinfo=timezone.utc)
    FRESH = "2026-08-19T00:00:00Z"

    def test_全店が新しければOK(self) -> None:
        rows = [_row(s, self.FRESH) for s in FLEET]
        detail, problems = weekly.build_detail(
            rows, min_stores=38, max_staleness_days=8, now=self.NOW, expected=FLEET
        )
        assert problems == []
        assert "- 公開済み店舗数（distinct store_slug）: 42 件" in detail
        assert "- 未公開の店舗: なし" in detail
        assert "- 陳腐化した店舗: なし" in detail

    def test_旧実装なら緑だった_1店だけ新しく残りが古い場合を検知する(self) -> None:
        """F8 の中核: 全体の最新1件だけでは緑になれてしまう典型パターン。"""
        rows = [_row("s0", self.FRESH)] + [
            _row(s, "2026-07-01T00:00:00Z") for s in FLEET[1:]
        ]
        detail, problems = weekly.build_detail(
            rows, min_stores=38, max_staleness_days=8, now=self.NOW, expected=FLEET
        )
        assert any(p.startswith("stale_stores=41") for p in problems), problems
        assert "陳腐化した店舗（8日超）: 41 件" in detail

    def test_特定店が欠けていれば未公開として検知する(self) -> None:
        rows = [_row(s, self.FRESH) for s in FLEET if s != "s5"]
        detail, problems = weekly.build_detail(
            rows, min_stores=38, max_staleness_days=8, now=self.NOW, expected=FLEET
        )
        assert any(p.startswith("missing=1(s5)") for p in problems), problems
        assert "未公開の店舗: 1 件 -> s5" in detail

    def test_STRICT_OFFなら旧挙動へ戻る(self) -> None:
        rows = [_row("s0", self.FRESH)] + [
            _row(s, "2026-07-01T00:00:00Z") for s in FLEET[1:]
        ]
        _detail, problems = weekly.build_detail(
            rows, min_stores=38, max_staleness_days=8, now=self.NOW,
            expected=FLEET, strict=False,
        )
        assert problems == []  # 旧実装（distinct 42 店・最新1件が1.0日前）と同じ判定

    def test_重複店舗は1店として数える(self) -> None:
        rows = [_row("s0", self.FRESH)] * 40
        _detail, problems = weekly.build_detail(
            rows, min_stores=38, max_staleness_days=8, now=self.NOW, expected=FLEET
        )
        assert "store_count=1<38" in problems

    def test_全店が古ければ陳腐化として問題になる(self) -> None:
        rows = [_row(s, "2026-08-01T00:00:00Z") for s in FLEET]
        detail, problems = weekly.build_detail(
            rows, min_stores=38, max_staleness_days=8, now=self.NOW, expected=FLEET
        )
        assert "staleness_days=19.0>8" in problems
        assert "-> 陳腐化！" in detail

    def test_該当レコードが無ければ判定不能として問題になる(self) -> None:
        detail, problems = weekly.build_detail(
            [], min_stores=38, max_staleness_days=8, now=self.NOW, expected=FLEET
        )
        assert "store_count=0<38" in problems
        assert "newest_updated_at unavailable" in problems
        assert "- 最新更新（全体）: 取得できませんでした（該当レコード無し）" in detail

    def test_最新のupdated_atを選ぶ_壊れた値は無視(self) -> None:
        rows = [
            _row("a", "not-a-date"),
            _row("b", "2026-08-18T10:00:00Z"),
            _row("c", "2026-08-19T10:00:00+00:00"),
            _row("d", None),
        ]
        assert weekly.newest_updated_at(rows) == datetime(2026, 8, 19, 10, 0, tzinfo=timezone.utc)

    def test_店舗別の最新値を選ぶ(self) -> None:
        rows = [
            _row("a", "2026-08-10T00:00:00Z"),
            _row("a", "2026-08-19T00:00:00Z"),
            _row("b", "bad"),
        ]
        got = weekly.newest_by_slug(rows)
        assert got == {"a": datetime(2026, 8, 19, tzinfo=timezone.utc)}

    def test_タイムゾーン無しの値はUTC扱い(self) -> None:
        assert weekly.newest_updated_at([_row("a", "2026-08-19T10:00:00")]) == datetime(
            2026, 8, 19, 10, 0, tzinfo=timezone.utc
        )

    def test_ちょうど基準日数はOK(self) -> None:
        rows = [_row(s, (self.NOW - timedelta(days=8)).isoformat()) for s in FLEET]
        _detail, problems = weekly.build_detail(
            rows, min_stores=38, max_staleness_days=8, now=self.NOW, expected=FLEET
        )
        assert problems == []


class Test設定不備の終了コード:
    def test_日次はSupabase未設定なら1で終わる(self, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
        assert daily.main() == 1
        assert "::error::SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY secret 未設定" in capsys.readouterr().out

    def test_週次はSupabase未設定なら1で終わる(self, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
        assert weekly.main() == 1
        assert "::error::SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY secret 未設定" in capsys.readouterr().out


class Test期待集合は店舗マスタが正本:
    def test_日次と週次で同じ42店を期待する(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ALLOWED_MISSING_SLUGS", raising=False)
        from scripts._stores_common import all_slugs

        assert daily.expected_slugs() == all_slugs()
        assert weekly.expected_slugs() == all_slugs()
