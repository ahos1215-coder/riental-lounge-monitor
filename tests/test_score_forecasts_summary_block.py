"""score_forecasts.py の「サマリ書き出し + アラート判定」ブロックの番犬（B-15）。

main() 全体（実ネットワーク・Supabase Storage を伴う）は動かさない。合成の
per_store / summary["nights"] を直接渡し、抽出した純関数が main() インライン時代と
同じ dict / 文字列 / 終了判定を返すことを固定する。
"""

from __future__ import annotations

from datetime import datetime, timezone

import scripts.score_forecasts as sf


def _entry(night: str, live: float | None, base: float | None, *, contaminated: bool = False) -> dict:
    return {
        "night_date": night,
        "overall_live_mae": live,
        "overall_baseline_mae": base,
        "stores_scored": 3,
        "overall_v2_mae": None,
        "captured_at_utc": None,
        "capture_minutes_late": None,
        "contaminated_capture": contaminated,
    }


class Test夜次サマリ行:
    def test_今夜の行の形が固定(self) -> None:
        captured = datetime(2026, 8, 18, 9, 10, tzinfo=timezone.utc)
        row = sf._summary_night_entry(
            night_date="20260818",
            overall=4.5,
            overall_baseline=5.0,
            stores_scored=7,
            overall_v2=4.9,
            captured_at=captured,
            capture_minutes_late=3,
            contaminated_capture=False,
        )
        assert row == {
            "night_date": "20260818",
            "overall_live_mae": 4.5,
            "overall_baseline_mae": 5.0,
            "stores_scored": 7,
            "overall_v2_mae": 4.9,
            "captured_at_utc": "2026-08-18T09:10:00+00:00",
            "capture_minutes_late": 3,
            "contaminated_capture": False,
        }

    def test_同じ夜の古い行は置き換えられ新しい順に並ぶ(self) -> None:
        existing = [_entry("20260817", 6.0, 6.5), _entry("20260818", 9.9, 9.9)]
        entry = _entry("20260818", 4.5, 5.0)
        merged = sf._merge_summary_nights(existing, entry)
        assert [n["night_date"] for n in merged] == ["20260818", "20260817"]
        assert merged[0]["overall_live_mae"] == 4.5

    def test_保持件数の上限が効く(self) -> None:
        existing = [_entry(f"2026{i:04d}", 1.0, 1.0) for i in range(1, 200)]
        merged = sf._merge_summary_nights(existing, _entry("20260818", 4.5, 5.0))
        assert len(merged) == sf.SUMMARY_KEEP


class Testアラート判定:
    def test_ベースラインに負けた夜はアラートになる(self) -> None:
        alerts, coverage_failure = sf._collect_accuracy_alerts(
            overall=6.0, overall_baseline=5.0,
            summary_nights=[_entry("20260818", 6.0, 5.0)],
            expected=3, stores_scored=3,
        )
        assert coverage_failure is False
        assert len(alerts) == 1
        assert "NOT beating the naive baseline" in alerts[0]

    def test_直近中央値の1_5倍を超えるとスパイク検知(self) -> None:
        nights = [_entry("20260818", 9.0, 20.0)] + [
            _entry(f"2026081{i}", 4.0, 20.0) for i in range(1, 6)
        ]
        alerts, _ = sf._collect_accuracy_alerts(
            overall=9.0, overall_baseline=20.0, summary_nights=nights,
            expected=3, stores_scored=3,
        )
        assert any("spiked" in a for a in alerts)

    def test_汚染夜は中央値の基準から外れる(self) -> None:
        """汚染夜だけが直近にあると比較対象が無くなり、スパイク検知は起きない。"""
        nights = [_entry("20260818", 9.0, 20.0)] + [
            _entry(f"2026081{i}", 4.0, 20.0, contaminated=True) for i in range(1, 6)
        ]
        alerts, _ = sf._collect_accuracy_alerts(
            overall=9.0, overall_baseline=20.0, summary_nights=nights,
            expected=3, stores_scored=3,
        )
        assert not any("spiked" in a for a in alerts)

    def test_採点カバレッジ9割未満は失敗扱い(self) -> None:
        alerts, coverage_failure = sf._collect_accuracy_alerts(
            overall=1.0, overall_baseline=9.0,
            summary_nights=[_entry("20260818", 1.0, 9.0)],
            expected=42, stores_scored=10,
        )
        assert coverage_failure is True
        assert any("Only 10/42 stores were scored" in a for a in alerts)

    def test_スナップショットが空ならカバレッジ失敗にしない(self) -> None:
        _alerts, coverage_failure = sf._collect_accuracy_alerts(
            overall=1.0, overall_baseline=9.0,
            summary_nights=[_entry("20260818", 1.0, 9.0)],
            expected=0, stores_scored=0,
        )
        assert coverage_failure is False
