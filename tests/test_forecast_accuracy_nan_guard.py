"""番犬: /api/forecast_accuracy の集計に NaN が混ざらないこと。

`_is_num` を postprocess 側の厳しい真理値表（bool も NaN/inf も除外）へ統一した
ことによる挙動確定テスト。旧実装は NaN を数値として通していたため、
per_store の relative_mae が NaN のまま JSON に載り（JSON では `NaN` リテラル）、
night_avg も NaN に化けることがあった。統一後は「そのキーが付かない」＝
フロントは欠損として扱う（精度カードが「参考値」表示へフォールバックする）。
"""

from __future__ import annotations

import math

from oriental.routes import forecast_accuracy as fc


def test_live_maeがNaNならrelative_maeを付けない():
    per_store = {"a": {"live_mae": float("nan"), "live_baseline_mae": 2.0}}
    fc._augment_relative_fields(per_store, {"a": 10.0})
    entry = per_store["a"]
    assert "relative_mae" not in entry
    # 比較不能なので beats_baseline も付けない
    assert "beats_baseline" not in entry
    # 店舗規模そのものは有効な値なので night_avg は従来どおり付く
    assert entry["night_avg"] == 10.0


def test_night_avgがNaNならrelative_maeもnight_avgも付けない():
    per_store = {"b": {"live_mae": 5.0, "live_baseline_mae": 2.0}}
    fc._augment_relative_fields(per_store, {"b": float("nan")})
    entry = per_store["b"]
    assert "night_avg" not in entry
    assert "relative_mae" not in entry
    assert entry["beats_baseline"] is False


def test_予測スナップショットの平均はNaNを無視する():
    snap = {"by_slug": {"x": [{"total_pred": float("nan")}, {"total_pred": 10.0}]}}
    out = fc._night_avg_by_store(snap)
    assert out == {"x": 10.0}
    assert not math.isnan(out["x"])


def test_実測夜間平均はNaNを採用しない():
    per_store = {"x": {"realized_night_avg": float("nan")}}
    assert fc._realized_night_avg_by_store(per_store) == {}
