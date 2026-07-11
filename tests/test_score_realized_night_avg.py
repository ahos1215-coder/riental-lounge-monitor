"""rank3 fix: scripts/score_forecasts.py が per_store に additive で書く
`realized_night_avg`（実測ベースの夜間平均）の永続化テスト（結合・モック・ネットワーク無し）。

背景: /api/forecast_accuracy の相対誤差 relative_mae は
`live_mae / night_avg` で店舗規模を正規化していたが、旧実装の night_avg は
「その夜の予測総数の平均」（accuracy/snapshots/<date>.json の by_slug）を使っていた。
これは自己参照バグを持つ: 過大予測している店ほど分母(night_avg)が大きくなり、
relative_mae が不当に小さく＝「高精度」に見えてしまう
（例: kagoshima は予測平均29.79 vs 実測23.4 -> 旧ロジックで過大評価）。

修正はここ(score_forecasts.py)で実測(REALIZED)の夜間平均を計算し、既存キーは一切
変えずに `realized_night_avg` として per_store に書き足す。分母の選択自体は
oriental/routes/forecast_accuracy.py 側（tests/test_forecast_accuracy_relative.py）
で検証する。ここでは「正しい値が正しいキーで永続化されること」「既存キーが
1つも失われないこと」を確認する。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

import scripts.score_forecasts as sf


def _install_common_mocks(monkeypatch, snapshot: dict, puts: dict, now_rows, prev_rows):
    monkeypatch.setattr(sf, "_load_env", lambda: None)
    monkeypatch.setenv("SUPABASE_URL", "http://x")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "k")
    monkeypatch.setenv("ACCURACY_FAIL_ON_BASELINE_LOSS", "0")  # exit code はテスト対象外
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    def fake_get(bucket, path, url, key):
        if path.startswith("accuracy/snapshots/"):
            return json.dumps(snapshot).encode()
        return None

    def fake_put(bucket, path, payload, url, key):
        puts[path] = json.loads(payload.decode())

    monkeypatch.setattr(sf, "_storage_get", fake_get)
    monkeypatch.setattr(sf, "_storage_put", fake_put)
    monkeypatch.setattr(sf, "_alert", lambda m: None)

    calls = {"i": 0}

    def fake_actuals(url, key, store_id, s_iso, e_iso):
        calls["i"] += 1
        return now_rows if calls["i"] % 2 == 1 else prev_rows

    monkeypatch.setattr(sf, "_fetch_actuals", fake_actuals)


def test_realized_night_avg_persisted_additively_and_matches_actual_mean(monkeypatch) -> None:
    night_date = (datetime.now(sf.JST) - timedelta(days=1)).strftime("%Y%m%d")
    base = datetime.strptime(night_date, "%Y%m%d").replace(tzinfo=sf.JST)
    slots = [base.replace(hour=19, minute=0) + timedelta(minutes=15 * i) for i in range(25)]

    # 予測は一律 total_pred=10.0（過大予測のシナリオ: 実測は 5..17 で平均11.0、
    # 予測平均が実測平均と一致しないことを保証し、自己参照バグとの違いを明確にする）。
    a_points = [{"ts": s.isoformat(), "total_pred": 10.0} for s in slots]
    snapshot = {"by_slug": {"shibuya": a_points}}

    now_totals = [5.0 + i * 0.5 for i in range(25)]  # 5.0..17.0, mean == 11.0 exactly
    now_rows = [{"ts": s.isoformat(), "total": v} for s, v in zip(slots, now_totals)]
    prev_rows = [{"ts": (s - timedelta(days=7)).isoformat(), "total": 8.0} for s in slots]

    puts: dict[str, dict] = {}
    _install_common_mocks(monkeypatch, snapshot, puts, now_rows, prev_rows)

    rc = sf.main()
    assert rc == 0

    scores = puts[f"accuracy/scores/{night_date}.json"]
    entry = scores["per_store"]["shibuya"]

    # --- 新規(additive)キー: 実測ベースの夜間平均 ---
    assert entry["realized_night_avg"] == pytest.approx(sum(now_totals) / len(now_totals))
    assert entry["realized_night_avg"] == pytest.approx(11.0)
    # 予測平均(10.0)とは異なる -> 自己参照(予測ベース)ではなく実測ベースである証拠
    assert entry["realized_night_avg"] != pytest.approx(10.0)

    # --- 既存キーは1つも失われていない(no key removed) ---
    assert entry["live_mae"] is not None
    assert entry["matched_slots"] == 25
    assert "live_baseline_mae" in entry
    assert "ml_vs_baseline_live_pct" in entry


def test_realized_night_avg_absent_when_no_matched_slots(monkeypatch) -> None:
    """マッチする実測スロットが無い店（ml_err が空）は、旧来どおり per_store に
    含めない（realized_night_avg も当然含まれない）——additive の範囲外は増やさない。"""
    night_date = (datetime.now(sf.JST) - timedelta(days=1)).strftime("%Y%m%d")
    base = datetime.strptime(night_date, "%Y%m%d").replace(tzinfo=sf.JST)
    slots = [base.replace(hour=19, minute=0) + timedelta(minutes=15 * i) for i in range(25)]

    a_points = [{"ts": s.isoformat(), "total_pred": 10.0} for s in slots]
    snapshot = {"by_slug": {"shibuya": a_points}}

    # 実測行が一件も返らない(空リスト) -> スロットが一切マッチしない
    now_rows: list[dict] = []
    prev_rows: list[dict] = []

    puts: dict[str, dict] = {}
    _install_common_mocks(monkeypatch, snapshot, puts, now_rows, prev_rows)

    sf.main()

    scores = puts[f"accuracy/scores/{night_date}.json"]
    assert "shibuya" not in scores["per_store"]
