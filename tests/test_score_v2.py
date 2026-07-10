"""score_forecasts.main() が v2/scorecard を additive に書くこと、既存 A キーが不変で
あることの結合テスト（ストレージ/実測はモック・ネットワーク無し）。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import scripts.score_forecasts as sf


def test_main_writes_v2_and_scorecard_additively(monkeypatch) -> None:
    monkeypatch.setattr(sf, "_load_env", lambda: None)
    monkeypatch.setenv("SUPABASE_URL", "http://x")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "k")
    monkeypatch.setenv("ACCURACY_FAIL_ON_BASELINE_LOSS", "0")  # exit code はテスト対象外
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    night_date = (datetime.now(sf.JST) - timedelta(days=1)).strftime("%Y%m%d")
    base = datetime.strptime(night_date, "%Y%m%d").replace(tzinfo=sf.JST)
    slots = [base.replace(hour=19, minute=0) + timedelta(minutes=15 * i) for i in range(25)]

    a_points = [{"ts": s.isoformat(), "total_pred": 10.0} for s in slots]
    v2_points = [
        {"ts": s.isoformat(), "total_pred": 9.0, "men_pred": 5.0, "women_pred": 4.0,
         "p10": 2.0, "p90": 30.0}
        for s in slots
    ]
    snapshot = {
        "by_slug": {"shibuya": a_points},
        "v2": {
            "shibuya": {
                "night_type": "H",
                "special_block": None,
                "template_generated_at": "2026-05-01T09:00:00+00:00",
                "template_fallback": None,
                "data": v2_points,
            }
        },
    }

    def fake_get(bucket, path, url, key):
        if path.startswith("accuracy/snapshots/"):
            return json.dumps(snapshot).encode()
        return None

    puts: dict[str, dict] = {}

    def fake_put(bucket, path, payload, url, key):
        puts[path] = json.loads(payload.decode())

    monkeypatch.setattr(sf, "_storage_get", fake_get)
    monkeypatch.setattr(sf, "_storage_put", fake_put)
    monkeypatch.setattr(sf, "_alert", lambda m: None)

    # 実測: ピークのある夜（peak_hit30 の有効条件 >=20 slots & peak>=5 を満たす）。
    now_totals = [5.0 + i * 0.5 for i in range(25)]  # 5..17、最大17
    now_rows = [{"ts": s.isoformat(), "total": v} for s, v in zip(slots, now_totals)]
    prev_rows = [{"ts": (s - timedelta(days=7)).isoformat(), "total": 8.0} for s in slots]
    calls = {"i": 0}

    def fake_actuals(url, key, store_id, s_iso, e_iso):
        calls["i"] += 1
        return now_rows if calls["i"] % 2 == 1 else prev_rows

    monkeypatch.setattr(sf, "_fetch_actuals", fake_actuals)

    rc = sf.main()
    assert rc == 0

    scores = puts.get(f"accuracy/scores/{night_date}.json")
    assert scores is not None

    # 既存 A キーは不変
    assert "overall_live_mae" in scores
    assert "per_store" in scores
    assert scores["per_store"]["shibuya"]["live_mae"] is not None

    # 追加された v2 ブロック
    assert "v2" in scores
    v2ps = scores["v2"]["per_store"]["shibuya"]
    assert v2ps["v2_mae"] is not None
    assert v2ps["night_type"] == "H"
    assert v2ps["band_coverage"] == 1.0  # 実測 5..17 は [2,30] に全て収まる
    assert scores["v2"]["overall_v2_mae"] is not None

    # 追加された scorecard ブロック（艦隊 + 店別）
    sc = scores["scorecard"]
    assert "a" in sc and "v2" in sc and "baseline" in sc
    assert "shibuya" in sc["per_store"]
    assert sc["per_store"]["shibuya"]["a"]["peak_hit30"] in (True, False)
    assert sc["per_store"]["shibuya"]["v2"]["band_coverage"] == 1.0

    # rolling summary の夜次エントリに overall_v2_mae が追加されている
    summ = puts.get("accuracy/scores/summary.json")
    assert summ is not None
    assert "overall_v2_mae" in summ["nights"][0]
