"""B1固定バグ#1: 精度測定のカンニング（開店後capture汚染）検知+除外のテスト。

snapshot_forecasts.py が書く captured_at_utc を score_forecasts.py が
「18:10 + 30分猶予 = 18:40 JST」のカットオフと比較し、遅れた夜を
contaminated_capture=true としてローリング集計（live_mae履歴・blend_weights）
から除外することを検証する（全てモック・ネットワーク無し）。
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

import scripts.score_forecasts as sf

JST = sf.JST


# --------------------------------------------------------------------------- #
# _capture_lateness: 18:40 JST 境界の厳密さ
# --------------------------------------------------------------------------- #

def _night_midnight(night_date: str) -> datetime:
    return datetime.strptime(night_date, "%Y%m%d").replace(tzinfo=JST)


def test_capture_on_time_not_contaminated():
    base = _night_midnight("20260716")
    captured = base.replace(hour=18, minute=10).astimezone(timezone.utc)
    minutes_late, contaminated = sf._capture_lateness(captured, base)
    assert minutes_late == 0.0
    assert contaminated is False


def test_capture_exactly_at_1840_cutoff_not_contaminated():
    # 18:10 + 30分 = 18:40 ちょうどは「超過」ではないので非汚染（厳密に > のみ汚染）
    base = _night_midnight("20260716")
    captured = base.replace(hour=18, minute=40).astimezone(timezone.utc)
    minutes_late, contaminated = sf._capture_lateness(captured, base)
    assert minutes_late == 30.0
    assert contaminated is False


def test_capture_one_minute_past_cutoff_is_contaminated():
    base = _night_midnight("20260716")
    captured = base.replace(hour=18, minute=41).astimezone(timezone.utc)
    minutes_late, contaminated = sf._capture_lateness(captured, base)
    assert minutes_late == 31.0
    assert contaminated is True


def test_capture_matches_real_audit_delay_range():
    # 実測8夜の遅延範囲 72-186分（19:22-21:16 JST）— 両端とも汚染判定になること。
    base = _night_midnight("20260716")
    low = base.replace(hour=19, minute=22).astimezone(timezone.utc)
    high = base.replace(hour=21, minute=16).astimezone(timezone.utc)
    ml_low, c_low = sf._capture_lateness(low, base)
    ml_high, c_high = sf._capture_lateness(high, base)
    assert ml_low == pytest.approx(72.0)
    assert ml_high == pytest.approx(186.0)
    assert c_low is True
    assert c_high is True


def test_capture_missing_is_unknown_not_contaminated():
    base = _night_midnight("20260716")
    minutes_late, contaminated = sf._capture_lateness(None, base)
    assert minutes_late is None
    assert contaminated is False


# --------------------------------------------------------------------------- #
# _uncontaminated_recent: フィルタ+件数上限
# --------------------------------------------------------------------------- #

def test_uncontaminated_recent_excludes_flagged_nights():
    nights = [
        {"night_date": "20260716", "contaminated_capture": True},
        {"night_date": "20260715", "contaminated_capture": False},
        {"night_date": "20260714"},  # フィールド無し(過去分) -> 非汚染扱い
        {"night_date": "20260713", "contaminated_capture": True},
        {"night_date": "20260712", "contaminated_capture": False},
    ]
    out = sf._uncontaminated_recent(nights, limit=7)
    assert [n["night_date"] for n in out] == ["20260715", "20260714", "20260712"]


def test_uncontaminated_recent_respects_limit():
    nights = [{"night_date": str(i), "contaminated_capture": False} for i in range(10)]
    out = sf._uncontaminated_recent(nights, limit=3)
    assert len(out) == 3
    assert [n["night_date"] for n in out] == ["0", "1", "2"]


# --------------------------------------------------------------------------- #
# main() 統合: 汚染夜が accuracy/scores/<date>.json・summary.json に記録され、
# blend_weights の recent_dates から除外されることを確認する。
# --------------------------------------------------------------------------- #

def _wire_main(monkeypatch, *, capture_hour: int, capture_minute: int, existing_summary_nights: list[dict]):
    """Wire up sf.main() for a single-store run whose snapshot's captured_at_utc is
    at capture_hour:capture_minute JST on the scored night. Returns
    (night_date, puts, recorded) where `puts` records every _storage_put call and
    `recorded["night_dates"]` captures the night_dates fed into compute_blend_weights.
    """
    monkeypatch.setattr(sf, "_load_env", lambda: None)
    monkeypatch.setenv("SUPABASE_URL", "http://x")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "k")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    night_date = (datetime.now(JST) - timedelta(days=1)).strftime("%Y%m%d")
    base = datetime.strptime(night_date, "%Y%m%d").replace(tzinfo=JST)
    slot = base.replace(hour=23, minute=0, second=0, microsecond=0)
    captured = base.replace(hour=capture_hour, minute=capture_minute).astimezone(timezone.utc).isoformat()

    snapshot = {
        "by_slug": {"shibuya": [{"ts": slot.isoformat(), "total_pred": 50.0}]},
        "captured_at_utc": captured,
    }
    existing_summary = {"nights": existing_summary_nights}

    puts: list[tuple[str, dict]] = []

    def fake_get(bucket, path, url, key):
        if path.startswith("accuracy/snapshots/"):
            return json.dumps(snapshot).encode()
        if path == "accuracy/scores/summary.json":
            return json.dumps(existing_summary).encode()
        return None

    def fake_put(bucket, path, payload, url, key):
        puts.append((path, json.loads(payload.decode())))

    monkeypatch.setattr(sf, "_storage_get", fake_get)
    monkeypatch.setattr(sf, "_storage_put", fake_put)
    monkeypatch.setattr(sf, "_alert", lambda msg: None)

    now_rows = [{"ts": slot.isoformat(), "total": 48.0}]
    prev_rows = [{"ts": (slot - timedelta(days=7)).isoformat(), "total": 10.0}]
    calls = {"i": 0}

    def fake_actuals(url, key, store_id, s_iso, e_iso):
        calls["i"] += 1
        return now_rows if calls["i"] == 1 else prev_rows

    monkeypatch.setattr(sf, "_fetch_actuals", fake_actuals)

    recorded: dict = {}

    def fake_compute_blend_weights(bucket, url, key, night_dates):
        recorded["night_dates"] = list(night_dates)
        return {}

    monkeypatch.setattr(sf, "compute_blend_weights", fake_compute_blend_weights)

    return night_date, captured, puts, recorded


def test_main_flags_late_capture_and_excludes_it_from_blend_dates(monkeypatch):
    # tonight was captured at 19:22 JST (audit's own minimum observed delay) — contaminated.
    night_date, captured, puts, recorded = _wire_main(
        monkeypatch,
        capture_hour=19,
        capture_minute=22,
        existing_summary_nights=[
            {"night_date": "20260101", "overall_live_mae": 5.0, "contaminated_capture": True},
            {"night_date": "20260102", "overall_live_mae": 6.0, "contaminated_capture": False},
        ],
    )

    rc = sf.main()
    assert rc in (0, 1)  # exit code depends on baseline comparison, not under test here

    # tonight's own scored doc is flagged contaminated with the right lateness.
    score_doc = next(doc for path, doc in puts if path == f"accuracy/scores/{night_date}.json")
    assert score_doc["contaminated_capture"] is True
    assert score_doc["capture_minutes_late"] == pytest.approx(72.0)
    assert score_doc["captured_at_utc"] == captured

    # summary.json's newest entry (tonight) carries the same flag for provenance.
    summary_doc = next(doc for path, doc in puts if path == "accuracy/scores/summary.json")
    assert summary_doc["nights"][0]["night_date"] == night_date
    assert summary_doc["nights"][0]["contaminated_capture"] is True

    # blend_weights recent_dates excludes BOTH the pre-existing contaminated night
    # (20260101) AND tonight itself (also contaminated) — only the clean night remains.
    assert "20260101" not in recorded["night_dates"]
    assert night_date not in recorded["night_dates"]
    assert "20260102" in recorded["night_dates"]


def test_main_includes_on_time_night_in_blend_dates(monkeypatch):
    night_date, captured, puts, recorded = _wire_main(
        monkeypatch,
        capture_hour=18,
        capture_minute=15,  # well within the 30-minute grace window
        existing_summary_nights=[
            {"night_date": "20260102", "overall_live_mae": 6.0, "contaminated_capture": False},
        ],
    )

    sf.main()

    score_doc = next(doc for path, doc in puts if path == f"accuracy/scores/{night_date}.json")
    assert score_doc["contaminated_capture"] is False
    assert score_doc["capture_minutes_late"] == pytest.approx(5.0)
    assert score_doc["captured_at_utc"] == captured

    # on-time night IS included in the blend-weights recent_dates.
    assert night_date in recorded["night_dates"]
    assert "20260102" in recorded["night_dates"]
