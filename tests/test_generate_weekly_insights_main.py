"""週次レポート生成 main() の出力を固定する番犬（B-06 / B-15）。

死蔵コードの撤去（megribi_score の動的ロード等）と main() の店舗ループ抽出を行っても、
書き出す JSON が1バイトも変わらないことを保証する。

ネットワークには出ない: `_load_rows`（/api/range フェッチ）だけを固定データに差し替え、
出力先も tmp_path に逃がす（Supabase 同期は既定 OFF のまま）。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

import scripts.generate_weekly_insights as gwi

JST = timezone(timedelta(hours=9))


def _rows_for(store: str) -> list[dict[str, Any]]:
    """再現可能な合成の観測行（7夜 × 19:00-23:45 の15分刻み）。"""
    rows: list[dict[str, Any]] = []
    base = datetime(2026, 8, 11, 19, 0, tzinfo=JST)
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


def _run_main(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, store: str) -> dict[str, Any]:
    monkeypatch.setattr(gwi, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        gwi, "_load_rows", lambda *a, **k: _rows_for(store)
    )
    # 「収集が止まっている店」判定に引っかからないよう、合成データの最終夜を基準時刻にする
    fixed_now = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)

    class _FixedDatetime(gwi.datetime):  # type: ignore[misc,valid-type]
        @classmethod
        def now(cls, tz=None):  # noqa: ANN001
            return fixed_now if tz is not None else fixed_now.replace(tzinfo=None)

    monkeypatch.setattr(gwi, "datetime", _FixedDatetime)
    monkeypatch.setenv("INSIGHTS_STORES", store)
    monkeypatch.delenv("INSIGHTS_GENERATE_AI_COMMENTARY", raising=False)
    monkeypatch.delenv("INSIGHTS_SYNC_SUPABASE", raising=False)
    monkeypatch.setattr("sys.argv", ["generate_weekly_insights.py"])

    assert gwi.main() == 0

    out_dir = tmp_path / "frontend" / "content" / "insights" / "weekly" / store
    files = sorted(out_dir.glob("*.json"))
    assert len(files) == 1, f"出力 JSON が1本だけ書かれること: {files}"
    return json.loads(files[0].read_text(encoding="utf-8"))


# 生成物のうち、実行時刻に依存しないキー集合と代表値を固定する。
EXPECTED_TOP_LEVEL_KEYS = {
    "analysis_id",
    "type",
    "store",
    "generated_at",
    "period",
    "raw_fetch_period",
    "params",
    "metrics",
    "metric_interpretations",
    "windows",
    "top_windows",
    "day_hour_heatmap",
    "next_week_recommendations",
    "daily_summary",
}


def test_週次レポートJSONの形と中身が固定(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _run_main(tmp_path, monkeypatch, "shibuya")

    assert set(payload) == EXPECTED_TOP_LEVEL_KEYS
    assert payload["type"] == "weekly"
    assert payload["store"] == "shibuya"
    # params は「出力専用」の ideal / gender_weight も含めて契約として維持する
    assert set(payload["params"]) == {
        "threshold",
        "min_duration_minutes",
        "ideal",
        "gender_weight",
        "occupancy_baseline",
    }
    assert payload["params"]["threshold"] == 0.40
    assert payload["params"]["ideal"] == 0.7
    assert payload["params"]["gender_weight"] == 1.5
    assert payload["metrics"]["points_used"] == 140


def test_週次レポートJSONのSHA256が整理の前後で一致(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """generated_at 以外を丸ごとハッシュで固定する（B-06/B-15 の挙動不変の証明）。"""
    payload = _run_main(tmp_path, monkeypatch, "ay_chiba")
    payload.pop("generated_at")
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert digest == "52c948f10b95be83e735f577ad8e975062eadaa0b392a87d80efec77a51e5270"
