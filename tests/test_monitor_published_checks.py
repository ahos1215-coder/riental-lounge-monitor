"""監視スクリプト（日次/週次レポートの公開チェック）の単体テスト（B-10）。

もとは .github/workflows/check-daily-published.yml / check-weekly-published.yml の
YAML ヒアドキュメントに直書きされていて、テストから触れなかったロジック。
scripts/monitor/ へ移した上で、閾値判定・サマリ文言・終了コードを固定する。

Supabase へは一切アクセスしない（HTTP は差し替え or 引数で注入）。
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
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


class Test日次の件数判定:
    def test_両エディションが基準以上ならOK(self) -> None:
        detail, missing = daily.build_detail(
            "2026-08-19", 30, {"evening_preview": 41, "late_update": 40}
        )
        assert missing == []
        assert detail.splitlines() == [
            "日次レポート公開チェック（2026-08-19 JST, 基準=30/エディション）",
            "- evening_preview: 41 件 公開 OK",
            "- late_update: 40 件 公開 OK",
        ]

    def test_片方でも不足なら不足一覧に出る(self) -> None:
        detail, missing = daily.build_detail(
            "2026-08-19", 30, {"evening_preview": 41, "late_update": 3}
        )
        assert missing == ["late_update=3"]
        assert "- late_update: 3 件 公開 不足！" in detail

    def test_ちょうど基準値はOK(self) -> None:
        _detail, missing = daily.build_detail(
            "2026-08-19", 30, {"evening_preview": 30, "late_update": 30}
        )
        assert missing == []

    @pytest.mark.parametrize(
        ("header", "expected"),
        [("0-0/44", 44), ("0-0/0", 0), ("*/*", 0), ("", 0), ("0-0/", 0)],
    )
    def test_ContentRangeの総件数を読む(self, header: str, expected: int) -> None:
        assert daily.parse_content_range_total(header) == expected


def _row(slug: str, updated_at: str) -> dict:
    return {"store_slug": slug, "updated_at": updated_at}


class Test週次の店舗数と鮮度判定:
    NOW = datetime(2026, 8, 20, 0, 0, tzinfo=timezone.utc)

    def test_店舗数も鮮度も基準内ならOK(self) -> None:
        rows = [_row(f"s{i}", "2026-08-19T00:00:00Z") for i in range(38)]
        detail, problems = weekly.build_detail(
            rows, min_stores=38, max_staleness_days=8, now=self.NOW
        )
        assert problems == []
        assert "- 公開済み店舗数（distinct store_slug）: 38 件" in detail
        assert "（1.0 日前）" in detail

    def test_重複店舗は1店として数える(self) -> None:
        rows = [_row("shibuya", "2026-08-19T00:00:00Z")] * 40
        _detail, problems = weekly.build_detail(
            rows, min_stores=38, max_staleness_days=8, now=self.NOW
        )
        assert problems == ["store_count=1<38"]

    def test_古すぎる更新は陳腐化として問題になる(self) -> None:
        rows = [_row(f"s{i}", "2026-08-01T00:00:00Z") for i in range(38)]
        detail, problems = weekly.build_detail(
            rows, min_stores=38, max_staleness_days=8, now=self.NOW
        )
        assert problems == ["staleness_days=19.0>8"]
        assert "-> 陳腐化！" in detail

    def test_該当レコードが無ければ判定不能として問題になる(self) -> None:
        detail, problems = weekly.build_detail(
            [], min_stores=38, max_staleness_days=8, now=self.NOW
        )
        assert problems == ["store_count=0<38", "newest_updated_at unavailable"]
        assert "- 最新更新: 取得できませんでした（該当レコード無し）" in detail

    def test_最新のupdated_atを選ぶ_壊れた値は無視(self) -> None:
        rows = [
            _row("a", "not-a-date"),
            _row("b", "2026-08-18T10:00:00Z"),
            _row("c", "2026-08-19T10:00:00+00:00"),
            _row("d", None),
        ]
        assert weekly.newest_updated_at(rows) == datetime(2026, 8, 19, 10, 0, tzinfo=timezone.utc)

    def test_タイムゾーン無しの値はUTC扱い(self) -> None:
        assert weekly.newest_updated_at([_row("a", "2026-08-19T10:00:00")]) == datetime(
            2026, 8, 19, 10, 0, tzinfo=timezone.utc
        )


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
