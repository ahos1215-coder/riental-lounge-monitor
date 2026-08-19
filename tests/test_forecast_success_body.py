"""番犬: /api/forecast_* の成功エンベロープ `_success_body()` の契約を固定する。

3ハンドラ（next_hour / today / today_multi の内部フェッチ）が同じ dict を返すよう
1関数に集約したため、ここがレスポンス形状の唯一の定義。キーが増減すると
フロント（useStorePreviewData）とキャッシュ共有が壊れる。
"""

from __future__ import annotations

from oriental.routes.forecast import _forecast_params, _success_body

_EXPECTED_KEYS = {
    "ok",
    "data",
    "reasoning",
    "insufficient_history",
    "blend_w_ml",
    "blended_slots",
    "clamped_slots",
}


def test_成功エンベロープのキー集合が変わらない():
    body = _success_body({}, [])
    assert set(body.keys()) == _EXPECTED_KEYS


def test_service_の値をそのまま透過する():
    raw = {
        "ok": True,
        "store": "ol_shibuya",       # store / freq_min はレスポンスに載せない
        "freq_min": 15,
        "reasoning": {"signals": {"is_rainy": 1}, "notes": ["x"]},
        "insufficient_history": False,
        "blend_w_ml": 0.42,
        "blended_slots": 3,
        "clamped_slots": 1,
        "data": [{"ts": "2026-08-19T19:00:00+09:00"}],
    }
    points = [{"ts": "2026-08-19T19:00:00+09:00", "total_pred": 12.0}]
    body = _success_body(raw, points)
    assert body["ok"] is True
    assert body["data"] == points  # data は正規化済みの points 側で上書きされる
    assert body["reasoning"] == raw["reasoning"]
    assert body["insufficient_history"] is False
    assert body["blend_w_ml"] == 0.42
    assert body["blended_slots"] == 3
    assert body["clamped_slots"] == 1
    assert "store" not in body and "freq_min" not in body


def test_欠損時の既定値():
    body = _success_body({"insufficient_history": 1}, [])
    assert body["reasoning"] == {}
    assert body["insufficient_history"] is True  # bool へ正規化
    assert body["blend_w_ml"] is None
    assert body["blended_slots"] is None
    assert body["clamped_slots"] is None


def test_予測パラメータの既定値(monkeypatch):
    monkeypatch.delenv("FORECAST_FREQ_MIN", raising=False)
    monkeypatch.delenv("NIGHT_START_H", raising=False)
    monkeypatch.delenv("NIGHT_END_H", raising=False)
    assert _forecast_params() == (15, 19, 5)


def test_予測パラメータはenvで上書きできる_freqは1未満にならない(monkeypatch):
    monkeypatch.setenv("FORECAST_FREQ_MIN", "0")
    monkeypatch.setenv("NIGHT_START_H", "18")
    monkeypatch.setenv("NIGHT_END_H", "6")
    assert _forecast_params() == (1, 18, 6)
