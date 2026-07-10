"""snapshot_forecasts.py の v2 併記ロジックのテスト（テンプレはモック・ネットワーク無し）。

_v2_points の合成算術、_compute_v2 の鮮度ガード(>48h)・店未登録時の null 化を検証する。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import scripts.snapshot_forecasts as snap

JST = snap.JST


def _tmpl(scale: float = 100.0) -> dict:
    return {
        "shape": [1.0 / 40] * 40,
        "p10": [0.01] * 40,
        "p90": [0.04] * 40,
        "men_ratio": [0.6] * 40,
        "scale_ref": scale,
        "n_nights": 10,
        "fallback": None,
    }


def test_v2_points_math() -> None:
    t = {
        "shape": [0.25] + [0.75 / 39] * 39,
        "p10": [0.1] + [0.0] * 39,
        "p90": [0.2] + [0.0] * 39,
        "men_ratio": [0.6] + [0.5] * 39,
        "scale_ref": 200.0,
    }
    base = datetime(2026, 5, 2, 19, 0, tzinfo=JST)
    ts_list = [base + timedelta(minutes=15 * i) for i in range(40)]
    pts = snap._v2_points(t, ts_list)
    assert len(pts) == 40
    p0 = pts[0]
    assert p0["ts"] == base.isoformat()
    assert p0["total_pred"] == pytest.approx(50.0)   # 0.25 * 200
    assert p0["men_pred"] == pytest.approx(30.0)     # 50 * 0.6
    assert p0["women_pred"] == pytest.approx(20.0)   # 50 - 30
    assert p0["p10"] == pytest.approx(20.0)          # 0.1 * 200
    assert p0["p90"] == pytest.approx(40.0)          # 0.2 * 200


def test_compute_v2_fresh(monkeypatch) -> None:
    monkeypatch.setattr(snap, "classify_night", lambda d: "H")
    monkeypatch.setattr(snap, "special_block", lambda d: None)
    doc = {
        "schema": "v2t1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stores": {"ol_shibuya": {"H": _tmpl(100.0)}, "ay_ueno": {"H": _tmpl(80.0)}},
    }
    import json

    monkeypatch.setattr(snap, "_storage_get", lambda *a, **k: json.dumps(doc).encode())
    now_jst = datetime(2026, 5, 1, 18, 10, tzinfo=JST)
    out = snap._compute_v2(["shibuya", "ay_ueno", "gangnam"], "http://x", "k", "b", now_jst)

    assert out["shibuya"] is not None
    assert out["shibuya"]["night_type"] == "H"
    assert out["shibuya"]["special_block"] is None
    assert len(out["shibuya"]["data"]) == 40
    assert out["ay_ueno"] is not None
    # gangnam はテンプレに無い → null
    assert out["gangnam"] is None


def test_compute_v2_stale_returns_all_null(monkeypatch) -> None:
    import json

    doc = {
        "schema": "v2t1",
        "generated_at": (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat(),
        "stores": {"ol_shibuya": {"H": _tmpl()}},
    }
    monkeypatch.setattr(snap, "_storage_get", lambda *a, **k: json.dumps(doc).encode())
    out = snap._compute_v2(["shibuya"], "http://x", "k", "b", datetime.now(JST))
    assert out == {"shibuya": None}


def test_compute_v2_missing_returns_all_null(monkeypatch) -> None:
    monkeypatch.setattr(snap, "_storage_get", lambda *a, **k: None)
    out = snap._compute_v2(["shibuya", "ay_ueno"], "http://x", "k", "b", datetime.now(JST))
    assert out == {"shibuya": None, "ay_ueno": None}


# --------------------------------------------------------------------------- #
# v2.1 blend50: tonight スケールの stale-tonight ガード
# --------------------------------------------------------------------------- #
def _doc_with_tonight(tonight: dict | None) -> dict:
    st: dict = {"H": _tmpl(100.0)}  # scale_ref=100 → shape 1/40 → slot0 total=2.5
    if tonight is not None:
        st["tonight"] = tonight
    return {
        "schema": "v2t1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stores": {"ol_shibuya": st},
    }


def _run_compute(monkeypatch, doc: dict, now_jst: datetime):
    import json

    monkeypatch.setattr(snap, "classify_night", lambda d: "H")
    monkeypatch.setattr(snap, "special_block", lambda d: None)
    monkeypatch.setattr(snap, "_storage_get", lambda *a, **k: json.dumps(doc).encode())
    return snap._compute_v2(["shibuya"], "http://x", "k", "b", now_jst)


def test_tonight_guard_match_uses_blend50(monkeypatch) -> None:
    now_jst = datetime(2026, 5, 1, 18, 10, tzinfo=JST)
    doc = _doc_with_tonight(
        {"date": "2026-05-01", "night_type": "H", "scale_median": 100.0,
         "scale_lgbm": 500.0, "scale_blend50": 300.0}
    )
    out = _run_compute(monkeypatch, doc, now_jst)
    assert out["shibuya"]["scale_source"] == "blend50"
    # slot0 = shape[0](=1/40) × blend50(300) = 7.5（scale_ref の 2.5 ではない）
    assert out["shibuya"]["data"][0]["total_pred"] == pytest.approx(7.5)


def test_tonight_guard_date_mismatch_falls_back(monkeypatch) -> None:
    now_jst = datetime(2026, 5, 1, 18, 10, tzinfo=JST)
    doc = _doc_with_tonight(
        {"date": "2026-04-30", "night_type": "H", "scale_blend50": 300.0}  # 昨日の tonight
    )
    out = _run_compute(monkeypatch, doc, now_jst)
    assert out["shibuya"]["scale_source"] == "scale_ref"
    assert out["shibuya"]["data"][0]["total_pred"] == pytest.approx(2.5)  # scale_ref=100


def test_tonight_guard_type_mismatch_falls_back(monkeypatch) -> None:
    now_jst = datetime(2026, 5, 1, 18, 10, tzinfo=JST)
    doc = _doc_with_tonight(
        {"date": "2026-05-01", "night_type": "L", "scale_blend50": 300.0}  # 型が今夜(H)と不一致
    )
    out = _run_compute(monkeypatch, doc, now_jst)
    assert out["shibuya"]["scale_source"] == "scale_ref"
    assert out["shibuya"]["data"][0]["total_pred"] == pytest.approx(2.5)


def test_tonight_guard_missing_blend_falls_back(monkeypatch) -> None:
    now_jst = datetime(2026, 5, 1, 18, 10, tzinfo=JST)
    doc = _doc_with_tonight({"date": "2026-05-01", "night_type": "H"})  # scale_blend50 欠如
    out = _run_compute(monkeypatch, doc, now_jst)
    assert out["shibuya"]["scale_source"] == "scale_ref"


def test_tonight_absent_defaults_to_scale_ref(monkeypatch) -> None:
    now_jst = datetime(2026, 5, 1, 18, 10, tzinfo=JST)
    out = _run_compute(monkeypatch, _doc_with_tonight(None), now_jst)
    assert out["shibuya"]["scale_source"] == "scale_ref"
    assert out["shibuya"]["data"][0]["total_pred"] == pytest.approx(2.5)
