"""「特別な夜は2年残す」（2026-09-26 オーナー要望）の番犬。

背景:
  DB 容量（無料プラン 500MB）に収めるため、logs は行数上限（145万行）を超えたら古い順に消す。
  普段の夜は約8〜9か月で消えるが、年末年始・クリスマス・GW・お盆・大型連休の夜は「去年の同じ夜」
  と比べる価値がある（予測でもこれらは普段の夜を参考にできず、special_block で参照から外している）。
  そこで緊急削除は、直近2年の特別な夜を飛ばして、その次に古い普段の夜から消す。

ネットワークには出ない（_rest_get / delete_by_ids を差し替える）。本番の PostgREST で
and=(...) の絞り込みが通り、12/24〜1/4 の夜を飛ばして 1/5 の夜を返すことは 2026-09-26 に
読み取り専用の GET で確認済み。
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest
import yaml

from scripts import cleanup_old_logs as cleanup

REPO_ROOT = Path(__file__).resolve().parents[1]


class Test特別な夜の判定:
    @pytest.mark.parametrize(
        "night",
        [
            date(2025, 12, 24),  # クリスマスイブ
            date(2025, 12, 25),  # クリスマス
            date(2025, 12, 31),  # 年末年始
            date(2026, 1, 2),
            date(2026, 5, 3),  # GW
            date(2026, 8, 14),  # お盆
            date(2026, 9, 18),  # シルバーウィーク（9/19〜23 の5連休）の前夜
            date(2026, 9, 21),  # シルバーウィーク
            date(2026, 10, 31),  # ハロウィン
        ],
    )
    def test_特別な夜(self, night: date) -> None:
        assert cleanup.is_special_night(night)

    @pytest.mark.parametrize(
        "night",
        [
            date(2026, 6, 10),  # 普段の水曜
            date(2026, 6, 12),  # 普段の金曜
            date(2026, 11, 20),  # 普段の金曜
            date(2026, 7, 18),  # 3連休（海の日）の土曜＝4連休未満
        ],
    )
    def test_普段の夜(self, night: date) -> None:
        assert not cleanup.is_special_night(night)

    def test_年に30夜前後に収まる(self) -> None:
        """多すぎると普段の夜の保持を削りすぎる（年に約30夜＝約15万行を想定して容量を見積もった）。"""
        nights = [date(2026, 1, 1).fromordinal(date(2026, 1, 1).toordinal() + i) for i in range(365)]
        count = sum(cleanup.is_special_night(n) for n in nights)
        assert 15 <= count <= 40


class Test時間帯:
    def test_夜の時間帯はJST6時から翌6時(self) -> None:
        start, end = cleanup.night_window_utc(date(2025, 12, 24))
        assert start == datetime(2025, 12, 23, 21, 0, tzinfo=timezone.utc)
        assert end == datetime(2025, 12, 24, 21, 0, tzinfo=timezone.utc)

    def test_続いた夜は1つの範囲にまとめる(self) -> None:
        ranges = cleanup.special_night_ranges(date(2026, 9, 26), "2026-01-10T00:00:00+00:00", keep_days=300)
        # 2025-12-24〜2026-01-04 の夜（クリスマス〜年末年始の連休）は1つの範囲
        assert (
            datetime(2025, 12, 23, 21, 0, tzinfo=timezone.utc),
            datetime(2026, 1, 4, 21, 0, tzinfo=timezone.utc),
        ) in ranges

    def test_保護境界より新しい夜と2年より前の夜は含めない(self) -> None:
        ranges = cleanup.special_night_ranges(date(2026, 9, 26), "2026-03-01T00:00:00+00:00", keep_days=730)
        assert ranges
        assert all(start >= datetime(2024, 9, 25, 21, 0, tzinfo=timezone.utc) for start, _ in ranges)
        # GW 2026（保護境界より新しい）は入らない
        assert all(start < datetime(2026, 3, 1, 21, 0, tzinfo=timezone.utc) for start, _ in ranges)

    def test_絞り込みの書式(self) -> None:
        ranges = [(datetime(2025, 12, 23, 21, tzinfo=timezone.utc), datetime(2026, 1, 4, 21, tzinfo=timezone.utc))]
        assert cleanup.deletable_filter("2026-03-01T00:00:00.123456+00:00", ranges) == (
            '(ts.lt."2026-03-01T00:00:00Z",'
            'not.and(ts.gte."2025-12-23T21:00:00Z",ts.lt."2026-01-04T21:00:00Z"))'
        )


class Test緊急削除:
    def test_特別な夜を除く条件で古い順に消す(self, monkeypatch: pytest.MonkeyPatch) -> None:
        gets: list[dict] = []
        pages = [[{"id": 1}, {"id": 2}], [{"id": 3}], []]
        deleted_ids: list[list] = []

        def fake_get(path, params=None):
            gets.append(params)
            return pages.pop(0)

        monkeypatch.setattr(cleanup, "_rest_get", fake_get)
        monkeypatch.setattr(cleanup, "delete_by_ids", lambda ids, dry_run: deleted_ids.append(ids) or len(ids))

        deleted = cleanup.emergency_delete_oldest(
            current_count=1_500_000,
            max_rows=1_450_000,
            dry_run=False,
            protect_cutoff_iso="2026-03-01T00:00:00+00:00",
            protected_count=1_000_000,
            today=date(2026, 9, 26),
        )

        # 消せる行が尽きたらそこで止まる（1/5 の夜以降に普段の夜が無い、などの状況）
        assert deleted == 3
        assert deleted_ids == [[1, 2], [3]]
        first = gets[0]
        assert first["order"] == "ts.asc"
        assert "ts" not in first  # 旧実装の「保護境界より古い全部」ではない
        assert first["and"].startswith('(ts.lt."2026-03-01T00:00:00Z",')
        assert 'not.and(ts.gte."2025-12-23T21:00:00Z",ts.lt."2026-01-04T21:00:00Z")' in first["and"]

    def test_dryrunは従来どおり候補を取りに行かない(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(cleanup, "_rest_get", lambda *a, **k: pytest.fail("dry-run must not fetch"))
        assert cleanup.emergency_delete_oldest(
            current_count=1_500_000,
            max_rows=1_450_000,
            dry_run=True,
            protect_cutoff_iso="2026-03-01T00:00:00+00:00",
            protected_count=1_000_000,
        ) == 1_500_000 - int(1_450_000 * 0.95)


def test_間引きは特別な夜を残す期間より後にしか始まらない() -> None:
    """間引き（30分刻み）が先に来ると、去年と比べるために残した特別な夜を粗くしてしまう。"""
    assert cleanup.DOWNSAMPLE_AFTER_DAYS >= cleanup.SPECIAL_KEEP_DAYS >= 365


def test_ワークフローは祝日判定の部品を入れてから走る() -> None:
    doc = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "cleanup-old-logs.yml").read_text(encoding="utf-8"))
    for job in doc["jobs"].values():
        names = [step.get("name", "") for step in job.get("steps", [])]
        if "Run cleanup" not in names:
            continue
        install = next(i for i, step in enumerate(job["steps"]) if "jpholiday" in str(step.get("run", "")))
        assert install < names.index("Run cleanup")
        return
    pytest.fail("Run cleanup step not found")
