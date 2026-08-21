"""F14 番犬: 週報の日付ラベルは JST で作る（UTC 基準だと火曜日付になる）。

背景（外部レビュー 2026-08-21 F14）:
週次生成は水曜 06:30 JST（Task Scheduler `MEGRIBI-weekly`）に走るが、その瞬間は
火曜 21:30 UTC。旧実装は `datetime.now(timezone.utc).date()` を `date_label` にして
いたため、公開週報の `target_date`・生成 JSON のファイル名（`<date_label>.json`）・
sitemap の lastModified（そのファイル名を見る）が1日前の火曜になっていた。

波及は上記3つに限られる（一覧の並びは created_at、週次監視は updated_at と店舗集合を
見るため影響なし＝第2ラウンドで訂正済み）。過去に生成済みの JSON はリネームしない。

ネットワークには出ない（_load_rows を固定データに差し替え、出力先も tmp_path）。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

import scripts.generate_weekly_insights as gwi

JST = timezone(timedelta(hours=9))


def _rows_for(store: str, last_night: datetime) -> list[dict[str, Any]]:
    """last_night を最終夜とする7夜ぶんの合成観測行（19:00-23:45 の15分刻み）。"""
    rows: list[dict[str, Any]] = []
    base = last_night.replace(hour=19, minute=0, second=0, microsecond=0) - timedelta(days=6)
    for night in range(7):
        for slot in range(20):
            ts = base + timedelta(days=night, minutes=15 * slot)
            men = 6 + (night * 2 + slot) % 9
            women = 4 + (night * 3 + slot) % 7
            rows.append({
                "ts": ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                "store_id": store,
                "men": men,
                "women": women,
                "total": men + women,
            })
    return rows


def _run_main(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, now_utc: datetime) -> tuple[str, dict]:
    store = "shibuya"
    monkeypatch.setattr(gwi, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        gwi, "_load_rows",
        lambda *a, **k: _rows_for(store, now_utc.astimezone(JST) - timedelta(days=1)),
    )

    class _FixedDatetime(gwi.datetime):  # type: ignore[misc,valid-type]
        @classmethod
        def now(cls, tz=None):  # noqa: ANN001
            return now_utc if tz is not None else now_utc.replace(tzinfo=None)

    monkeypatch.setattr(gwi, "datetime", _FixedDatetime)
    monkeypatch.setenv("INSIGHTS_STORES", store)
    monkeypatch.delenv("INSIGHTS_GENERATE_AI_COMMENTARY", raising=False)
    monkeypatch.delenv("INSIGHTS_SYNC_SUPABASE", raising=False)
    monkeypatch.setattr("sys.argv", ["generate_weekly_insights.py"])

    assert gwi.main() == 0

    out_dir = tmp_path / "frontend" / "content" / "insights" / "weekly" / store
    files = sorted(out_dir.glob("*.json"))
    assert len(files) == 1, files
    return files[0].name, json.loads(files[0].read_text(encoding="utf-8"))


class Test週報の日付ラベル:
    def test_水曜0630JSTの実行は水曜日付になる(self, tmp_path: Path, monkeypatch) -> None:
        # 2026-08-19(水) 06:30 JST == 2026-08-18(火) 21:30 UTC
        now_utc = datetime(2026, 8, 18, 21, 30, tzinfo=timezone.utc)
        name, payload = _run_main(tmp_path, monkeypatch, now_utc=now_utc)

        assert name == "2026-08-19.json"          # 旧実装は 2026-08-18.json
        assert payload["analysis_id"].endswith(":2026-08-19")
        # generated_at（機械可読の生成時刻）は UTC のまま
        assert payload["generated_at"].startswith("2026-08-18T21:30")

    def test_JST日中の実行はUTCと同じ日付のまま(self, tmp_path: Path, monkeypatch) -> None:
        # 2026-08-19(水) 21:00 JST == 同日 12:00 UTC（日付が跨がないケースは不変）
        now_utc = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)
        name, payload = _run_main(tmp_path, monkeypatch, now_utc=now_utc)

        assert name == "2026-08-19.json"
        assert payload["analysis_id"].endswith(":2026-08-19")
