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

from scripts.backup_logs import backoff_delay as backup_backoff_delay
from scripts.backup_logs import check_row_count_sane
from scripts.cleanup_old_logs import backoff_delay as cleanup_backoff_delay
from scripts.cleanup_old_logs import emergency_delete_oldest, is_retryable_status


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


class TestRetryPolicy:
    """2026-08-09 以降のクラウド全滅（Supabase 飽和）に対する再試行方針のテスト。

    backup / cleanup はいずれも Supabase を1000行ずつ約1,300回叩くため、
    「1回のブリップで全体が死ぬ」旧実装（backup=4回/合計12秒、cleanup=再試行なし）
    では約1,300回の試行を生き延びられなかった。
    """

    def test_backup_backoff_is_exponential_and_capped(self) -> None:
        assert backup_backoff_delay(1, cap=45) == 2
        assert backup_backoff_delay(2, cap=45) == 4
        assert backup_backoff_delay(3, cap=45) == 8
        # 上限で頭打ちになる（無限に伸びない）
        assert backup_backoff_delay(10, cap=45) == 45

    def test_backup_backoff_honours_larger_retry_after(self) -> None:
        """429 too_many_connections に付く Retry-After が計算値より大きければ従う。"""
        assert backup_backoff_delay(1, retry_after=30, cap=45) == 30

    def test_backup_backoff_ignores_smaller_retry_after(self) -> None:
        """Retry-After が計算値より小さければ、こちらのバックオフを優先する。"""
        assert backup_backoff_delay(4, retry_after=1, cap=45) == 16

    def test_backup_backoff_retry_after_still_capped(self) -> None:
        """異常に長い Retry-After を渡されても上限を超えない。"""
        assert backup_backoff_delay(1, retry_after=9999, cap=45) == 45

    def test_backup_total_budget_survives_a_multi_minute_wobble(self) -> None:
        """旧実装(4回/合計12秒)では吸収できなかった数分の混雑を吸収できること。"""
        total = sum(backup_backoff_delay(a, cap=45) for a in range(1, 10))
        assert total >= 180  # 3分以上は粘る

    def test_cleanup_backoff_is_exponential_and_capped(self) -> None:
        assert cleanup_backoff_delay(1, cap=45) == 2
        assert cleanup_backoff_delay(3, cap=45) == 8
        assert cleanup_backoff_delay(10, cap=45) == 45

    def test_saturation_statuses_are_retryable(self) -> None:
        """Supabase の飽和シグナルはすべて再試行対象。

        429=too_many_connections/SlowDown, 500=statement timeout,
        544=DatabaseTimeout（2026-08-17 の学習ジョブが受け取った実際のコード）。
        """
        for code in (429, 500, 502, 503, 504, 544):
            assert is_retryable_status(code) is True, code

    def test_client_errors_are_not_retryable(self) -> None:
        """認証ミスや不正クエリを再試行しても無駄なので即座に失敗させる。"""
        for code in (400, 401, 403, 404, 409, 422):
            assert is_retryable_status(code) is False, code
