"""運用安全系スクリプトのユニットテスト（ネットワーク不使用の純粋ロジックのみ）。

対象:
- scripts/cleanup_old_logs.py: emergency_delete_oldest の ML 学習ウィンドウ保護
  （PROTECT_DAYS より新しい行は緊急削除で絶対に消さない）
- scripts/backup_logs.py: check_row_count_sane の行数健全性チェック
  （2026-07-06 に発覚した「107万行中1000行しかバックアップされていないのに
  total==0 チェックだけでは成功扱いされた」事故の再発防止）

いずれも Supabase への実ネットワークアクセスは行わない（dry_run / 純粋関数のみ）。
"""

from __future__ import annotations

from scripts.backup_logs import check_row_count_sane
from scripts.cleanup_old_logs import emergency_delete_oldest


class TestEmergencyDeleteOldestFloorProtection:
    def test_deletes_full_excess_when_floor_not_at_risk(self) -> None:
        """保護対象より古い行が十分にあれば、通常どおり95%ターゲットまで削除する。"""
        deleted = emergency_delete_oldest(
            current_count=3_200_000,
            max_rows=3_000_000,
            dry_run=True,
            protect_cutoff_iso="2026-01-01T00:00:00+00:00",
            protected_count=900_000,
        )
        assert deleted == 350_000  # excess = 3_200_000 - 2_850_000(target)

    def test_caps_deletion_at_floor_when_would_otherwise_breach(self) -> None:
        """削除可能行数がフロアで制限される場合、それ以上は絶対に削除しない。"""
        deleted = emergency_delete_oldest(
            current_count=3_200_000,
            max_rows=3_000_000,
            dry_run=True,
            protect_cutoff_iso="2026-06-01T00:00:00+00:00",
            protected_count=3_100_000,  # ほぼ全部が ML ウィンドウ内 = 削除可能は10万行のみ
        )
        # 本来の excess(350,000) より少ない 100,000 に制限される
        assert deleted == 100_000

    def test_refuses_all_deletion_when_fully_protected(self) -> None:
        """保護対象がテーブル全体をカバーする場合、緊急削除は何もしない（フロア死守）。"""
        deleted = emergency_delete_oldest(
            current_count=3_200_000,
            max_rows=3_000_000,
            dry_run=True,
            protect_cutoff_iso="2026-07-01T00:00:00+00:00",
            protected_count=3_200_000,
        )
        assert deleted == 0

    def test_noop_when_under_max_rows(self) -> None:
        """上限を超えていなければ、保護状態に関わらず何もしない。"""
        deleted = emergency_delete_oldest(
            current_count=2_000_000,
            max_rows=3_000_000,
            dry_run=True,
            protect_cutoff_iso="2026-01-01T00:00:00+00:00",
            protected_count=100_000,
        )
        assert deleted == 0


class TestBackupRowCountSanity:
    def test_exact_match_is_sane(self) -> None:
        is_sane, _ = check_row_count_sane(total=1_074_907, db_count=1_074_907)
        assert is_sane is True

    def test_small_concurrent_growth_within_tolerance_is_sane(self) -> None:
        """ダンプ中に収集が新規行を挿入しても、許容誤差内なら健全と判定する。"""
        is_sane, _ = check_row_count_sane(total=1_074_907, db_count=1_074_907 + 500)
        assert is_sane is True

    def test_incident_repro_is_flagged_insane(self) -> None:
        """2026-07-06 事故の再現: 107万行中1000行しかダンプできていない場合は不健全と判定する。"""
        is_sane, min_acceptable = check_row_count_sane(total=1000, db_count=1_074_907)
        assert is_sane is False
        assert min_acceptable > 1000

    def test_just_within_tolerance_boundary_is_sane(self) -> None:
        db_count = 1_000_000
        total = int(db_count * (1 - 0.02))  # ちょうど2%不足
        is_sane, min_acceptable = check_row_count_sane(total=total, db_count=db_count)
        assert is_sane is True
        assert min_acceptable == total

    def test_just_beyond_tolerance_boundary_is_insane(self) -> None:
        db_count = 1_000_000
        total = int(db_count * 0.97)  # 3%不足 -> 許容誤差(2%)を超える
        is_sane, _ = check_row_count_sane(total=total, db_count=db_count)
        assert is_sane is False
