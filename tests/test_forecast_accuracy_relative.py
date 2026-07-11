"""/api/forecast_accuracy の相対精度フィールド（additive）のテスト。

精度バッジを「絶対人数の MAE」ではなく「店舗規模に対する相対性能」で判定できるよう、
バックエンドが per_store に付与するフィールドを検証する:
  - beats_baseline: live_mae < live_baseline_mae（ナイーブ基準に勝っているか）
  - night_avg:      想定夜間来客数（相対誤差の分母）
  - night_avg_source: night_avg の由来 "realized"|"predicted"
  - relative_mae:   live_mae / night_avg（店舗規模で正規化した相対誤差）

rank3 fix (2026-07): night_avg は本来 実測(REALIZED) の夜間平均を優先して使う
(scripts/score_forecasts.py が per_store に additive で書く `realized_night_avg`)。
旧フォーマットの日次スコア（`realized_night_avg` が無い）は、過大予測ほど分母が
膨らむ自己参照バグを持つ「予測」総数の平均（_night_avg_by_store）へ一時的に
フォールバックする。night_avg_source フィールドでどちらを使ったか常に判別できる。

純関数 (_night_avg_by_store / _realized_night_avg_by_store / _augment_relative_fields)
はネットワーク無しで、エンドポイントは _storage_get（urllib）をモックして検証する。
既存キー（mae_7d 等）が壊れていないことも確認する（後方互換＝追加のみ）。
"""

from __future__ import annotations

import json

import pytest

from oriental import create_app
from oriental.routes import forecast_accuracy as fc


# --------------------------------------------------------------------------- #
# 純関数: _night_avg_by_store
# --------------------------------------------------------------------------- #
class TestNightAvgByStore:
    def test_averages_total_pred_per_store(self) -> None:
        snap = {
            "by_slug": {
                "shibuya": [{"total_pred": 40.0}, {"total_pred": 50.0}],  # avg 45
                "utsunomiya": [{"total_pred": 3.0}, {"total_pred": 4.0}],  # avg 3.5
            }
        }
        out = fc._night_avg_by_store(snap)
        assert out["shibuya"] == pytest.approx(45.0)
        assert out["utsunomiya"] == pytest.approx(3.5)

    def test_ignores_non_numeric_and_bool_and_missing(self) -> None:
        snap = {
            "by_slug": {
                # bool は数値扱いしない、欠損/文字列は無視、有効値だけで平均
                "a": [{"total_pred": True}, {"total_pred": "x"}, {"total_pred": 10.0}, {"nope": 1}],
                "b": [{"total_pred": None}],  # 有効値ゼロ -> 結果に含めない
                "c": "not-a-list",
            }
        }
        out = fc._night_avg_by_store(snap)
        assert out == {"a": pytest.approx(10.0)}

    @pytest.mark.parametrize("bad", [None, {}, {"by_slug": None}, {"by_slug": []}, 42])
    def test_returns_empty_on_bad_input(self, bad) -> None:
        assert fc._night_avg_by_store(bad) == {}


# --------------------------------------------------------------------------- #
# 純関数: _realized_night_avg_by_store（rank3 fix の本体）
# --------------------------------------------------------------------------- #
class TestRealizedNightAvgByStore:
    def test_reads_realized_night_avg_key(self) -> None:
        # scripts/score_forecasts.py が additive に書く実測ベースの夜間平均をそのまま拾う。
        per_store = {
            "kagoshima": {"live_mae": 5.0, "realized_night_avg": 23.4},
            "nagoya_sakae": {"live_mae": 4.0, "realized_night_avg": 18.2},
        }
        out = fc._realized_night_avg_by_store(per_store)
        assert out == {"kagoshima": pytest.approx(23.4), "nagoya_sakae": pytest.approx(18.2)}

    def test_missing_key_excluded_old_format(self) -> None:
        # rank3 fix 以前に書かれたスコアには realized_night_avg が無い -> 結果に含めない
        # （呼び出し側が _night_avg_by_store へフォールバックする対象になる）。
        per_store = {"shibuya": {"live_mae": 11.78}}
        assert fc._realized_night_avg_by_store(per_store) == {}

    def test_zero_or_negative_excluded(self) -> None:
        per_store = {"a": {"realized_night_avg": 0.0}, "b": {"realized_night_avg": -1.0}}
        assert fc._realized_night_avg_by_store(per_store) == {}

    @pytest.mark.parametrize("bad", [None, {}, 42, "x"])
    def test_returns_empty_on_bad_input(self, bad) -> None:
        assert fc._realized_night_avg_by_store(bad) == {}


# --------------------------------------------------------------------------- #
# 純関数: _augment_relative_fields
# --------------------------------------------------------------------------- #
class TestAugmentRelativeFields:
    def test_beats_baseline_true_and_relative_computed(self) -> None:
        # shibuya 実データ相当: live 11.78 < baseline 22.29 -> 勝ち。規模 44.8。
        per_store = {"shibuya": {"live_mae": 11.78, "live_baseline_mae": 22.29}}
        fc._augment_relative_fields(per_store, {"shibuya": 44.8})
        e = per_store["shibuya"]
        assert e["beats_baseline"] is True
        assert e["night_avg"] == 44.8
        assert e["relative_mae"] == pytest.approx(round(11.78 / 44.8, 3))
        # 既存キーは不変（additive）
        assert e["live_mae"] == 11.78 and e["live_baseline_mae"] == 22.29
        # night_avg_source 未指定時は "predicted" 扱い（呼び出し元との後方互換）
        assert e["night_avg_source"] == "predicted"

    def test_night_avg_source_realized_when_provided(self) -> None:
        # rank3 fix: 呼び出し側が実測ベースの night_avg を渡した場合は "realized" と明示する。
        per_store = {"shibuya": {"live_mae": 11.78, "live_baseline_mae": 22.29}}
        fc._augment_relative_fields(per_store, {"shibuya": 23.4}, {"shibuya": "realized"})
        e = per_store["shibuya"]
        assert e["night_avg"] == 23.4
        assert e["night_avg_source"] == "realized"
        assert e["relative_mae"] == pytest.approx(round(11.78 / 23.4, 3))

    def test_night_avg_source_mixed_per_store(self) -> None:
        # 一部の店だけ realized、残りは predicted にフォールバックする移行期の混在ケース。
        per_store = {
            "shibuya": {"live_mae": 11.78, "live_baseline_mae": 22.29},
            "kashiwa": {"live_mae": 6.99, "live_baseline_mae": 4.02},
        }
        fc._augment_relative_fields(
            per_store,
            {"shibuya": 23.4, "kashiwa": 11.8},
            {"shibuya": "realized"},  # kashiwa は source 未指定 -> "predicted"
        )
        assert per_store["shibuya"]["night_avg_source"] == "realized"
        assert per_store["kashiwa"]["night_avg_source"] == "predicted"

    def test_worse_than_baseline_sets_beats_baseline_false(self) -> None:
        # kashiwa 実データ相当: live 6.99 > baseline 4.02 -> ナイーブ基準に負け。
        per_store = {"kashiwa": {"live_mae": 6.99, "live_baseline_mae": 4.02}}
        fc._augment_relative_fields(per_store, {"kashiwa": 11.8})
        assert per_store["kashiwa"]["beats_baseline"] is False
        assert per_store["kashiwa"]["relative_mae"] == pytest.approx(round(6.99 / 11.8, 3))

    def test_relative_mae_uses_store_scale_not_absolute(self) -> None:
        # 小規模店(utsunomiya)は小さい MAE でも相対誤差は大きい。逆に大規模店(shibuya)は
        # 大きい MAE でも相対誤差は小さい —— これが絶対人数の逆転を正す根拠。
        per_store = {
            "utsunomiya": {"live_mae": 2.39, "live_baseline_mae": 2.64},
            "shibuya": {"live_mae": 11.78, "live_baseline_mae": 22.29},
        }
        fc._augment_relative_fields(per_store, {"utsunomiya": 3.5, "shibuya": 44.8})
        # 絶対: utsunomiya(2.39) << shibuya(11.78) だが、相対は逆転する
        assert per_store["utsunomiya"]["relative_mae"] > per_store["shibuya"]["relative_mae"]

    def test_beats_baseline_set_without_snapshot_but_no_relative(self) -> None:
        # スナップショット(night_avg)が無くても beats_baseline は日次スコアだけで付く。
        per_store = {"shibuya": {"live_mae": 11.78, "live_baseline_mae": 22.29}}
        fc._augment_relative_fields(per_store, {})
        assert per_store["shibuya"]["beats_baseline"] is True
        assert "relative_mae" not in per_store["shibuya"]
        assert "night_avg" not in per_store["shibuya"]

    def test_missing_baseline_skips_beats_baseline(self) -> None:
        per_store = {"x": {"live_mae": 5.0}}  # baseline 無し
        fc._augment_relative_fields(per_store, {"x": 10.0})
        assert "beats_baseline" not in per_store["x"]
        assert per_store["x"]["relative_mae"] == pytest.approx(0.5)

    def test_zero_or_missing_night_avg_skips_relative(self) -> None:
        per_store = {"a": {"live_mae": 5.0, "live_baseline_mae": 6.0}}
        fc._augment_relative_fields(per_store, {"a": 0.0})  # avg<=0 -> スキップ
        assert "relative_mae" not in per_store["a"]
        assert "night_avg" not in per_store["a"]
        assert per_store["a"]["beats_baseline"] is True


# --------------------------------------------------------------------------- #
# エンドポイント統合: /api/forecast_accuracy
# --------------------------------------------------------------------------- #
class _FakeResp:
    def __init__(self, body: bytes):
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    # metadata.json（学習時 holdout metrics, store_id キー）
    meta = {
        "trained_at": "2026-07-09T00:00:00Z",
        "metrics": {
            "ol_shibuya": {"rows_test": 100, "overall": {"total_mae": 17.0, "men_mae": 8.0, "women_mae": 9.0}},
            "ol_kashiwa": {"rows_test": 80, "overall": {"total_mae": 3.6, "men_mae": 1.8, "women_mae": 1.8}},
        },
    }
    cache_dir = tmp_path / "ml_models"
    cache_dir.mkdir()
    (cache_dir / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")

    monkeypatch.setenv("FORECAST_MODEL_CACHE_DIR", str(cache_dir))
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "key")
    monkeypatch.setenv("FORECAST_MODEL_BUCKET", "ml-models")

    app = create_app()
    return app.test_client()


def _install_storage_mock(monkeypatch):
    summary = {
        "nights": [{"night_date": "20260709", "overall_live_mae": 6.82, "overall_baseline_mae": 8.07, "stores_scored": 2}],
        "updated_at_utc": "2026-07-09T22:00:00Z",
    }
    daily = {
        "per_store": {
            "shibuya": {"live_mae": 11.78, "matched_slots": 40, "live_baseline_mae": 22.29, "ml_vs_baseline_live_pct": 47.2},
            "kashiwa": {"live_mae": 6.99, "matched_slots": 40, "live_baseline_mae": 4.02, "ml_vs_baseline_live_pct": -74.0},
        }
    }
    snapshot = {
        "night_date": "20260709",
        "by_slug": {
            "shibuya": [{"total_pred": 40.0}, {"total_pred": 49.6}],  # avg 44.8
            "kashiwa": [{"total_pred": 11.0}, {"total_pred": 12.6}],  # avg 11.8
        },
    }

    def _fake_urlopen(req, timeout=10):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "accuracy/scores/summary.json" in url:
            return _FakeResp(json.dumps(summary).encode())
        if "accuracy/scores/20260709.json" in url:
            return _FakeResp(json.dumps(daily).encode())
        if "accuracy/snapshots/20260709.json" in url:
            return _FakeResp(json.dumps(snapshot).encode())
        raise AssertionError(f"unexpected storage url: {url}")

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)


def test_endpoint_adds_relative_fields_additively(app_client, monkeypatch):
    """`daily` に realized_night_avg が無い(旧フォーマット)ケース: 予測平均へ
    フォールバックし、night_avg_source="predicted" が明示される（transition挙動）。"""
    _install_storage_mock(monkeypatch)
    resp = app_client.get("/api/forecast_accuracy")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True

    live = body["live"]
    # 既存キーは不変（後方互換）
    assert live["mae_7d"] == 6.82
    assert live["baseline_7d"] == 8.07
    assert live["nights_count"] == 1

    ps = live["per_store"]
    # shibuya: 大規模・ナイーブ基準に大勝ち -> beats_baseline True, 低い相対誤差
    sh = ps["shibuya"]
    assert sh["beats_baseline"] is True
    assert sh["night_avg"] == 44.8
    assert sh["night_avg_source"] == "predicted"  # 旧フォーマットなので一時フォールバック
    assert sh["relative_mae"] == pytest.approx(round(11.78 / 44.8, 3))
    # 既存キーが残っていること
    assert sh["live_mae"] == 11.78 and sh["ml_vs_baseline_live_pct"] == 47.2

    # kashiwa: ナイーブ基準に負け -> beats_baseline False（バッジは参考値に丸められる根拠）
    ka = ps["kashiwa"]
    assert ka["beats_baseline"] is False
    assert ka["night_avg_source"] == "predicted"
    assert ka["relative_mae"] == pytest.approx(round(6.99 / 11.8, 3))


def test_endpoint_prefers_realized_night_avg_over_predicted(app_client, monkeypatch):
    """rank3 fix: 新フォーマット(realized_night_avg あり)では実測平均を使い、
    予測スナップショットには一切アクセスしない（自己修復後は Storage read も消える）。"""
    summary = {
        "nights": [{"night_date": "20260710", "overall_live_mae": 6.0, "overall_baseline_mae": 8.0, "stores_scored": 2}],
        "updated_at_utc": "2026-07-10T22:00:00Z",
    }
    daily = {
        "per_store": {
            # kagoshima: 過大予測(pred avg 29.79) vs 実測(23.4) -> 旧ロジックなら分母が
            # 大きすぎて relative_mae が不当に小さくなる（"高精度" 誤判定の実例）。
            "kagoshima": {"live_mae": 7.09, "live_baseline_mae": 9.0, "realized_night_avg": 23.4},
            "nagoya_sakae": {"live_mae": 5.0, "live_baseline_mae": 9.0, "realized_night_avg": 18.2},
        }
    }

    def _fake_urlopen(req, timeout=10):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "accuracy/scores/summary.json" in url:
            return _FakeResp(json.dumps(summary).encode())
        if "accuracy/scores/20260710.json" in url:
            return _FakeResp(json.dumps(daily).encode())
        raise AssertionError(f"unexpected storage url (snapshot should not be fetched): {url}")

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)

    resp = app_client.get("/api/forecast_accuracy")
    assert resp.status_code == 200
    ps = resp.get_json()["live"]["per_store"]

    kg = ps["kagoshima"]
    assert kg["night_avg"] == 23.4
    assert kg["night_avg_source"] == "realized"
    assert kg["relative_mae"] == pytest.approx(round(7.09 / 23.4, 3))

    ns = ps["nagoya_sakae"]
    assert ns["night_avg"] == 18.2
    assert ns["night_avg_source"] == "realized"
    assert ns["relative_mae"] == pytest.approx(round(5.0 / 18.2, 3))


def test_endpoint_falls_back_per_store_when_realized_partially_missing(app_client, monkeypatch):
    """移行期の混在: 1店は realized_night_avg あり、もう1店は無い(旧フォーマット行が
    まだ残っている)場合、それぞれ独立に realized/predicted を選ぶ。"""
    summary = {
        "nights": [{"night_date": "20260710", "overall_live_mae": 6.0, "overall_baseline_mae": 8.0, "stores_scored": 2}],
        "updated_at_utc": "2026-07-10T22:00:00Z",
    }
    daily = {
        "per_store": {
            "shibuya": {"live_mae": 11.78, "live_baseline_mae": 22.29, "realized_night_avg": 23.4},
            "kashiwa": {"live_mae": 6.99, "live_baseline_mae": 4.02},  # realized_night_avg 無し
        }
    }
    snapshot = {
        "night_date": "20260710",
        "by_slug": {
            "kashiwa": [{"total_pred": 11.0}, {"total_pred": 12.6}],  # avg 11.8
        },
    }

    def _fake_urlopen(req, timeout=10):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "accuracy/scores/summary.json" in url:
            return _FakeResp(json.dumps(summary).encode())
        if "accuracy/scores/20260710.json" in url:
            return _FakeResp(json.dumps(daily).encode())
        if "accuracy/snapshots/20260710.json" in url:
            return _FakeResp(json.dumps(snapshot).encode())
        raise AssertionError(f"unexpected storage url: {url}")

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)

    resp = app_client.get("/api/forecast_accuracy")
    assert resp.status_code == 200
    ps = resp.get_json()["live"]["per_store"]

    assert ps["shibuya"]["night_avg_source"] == "realized"
    assert ps["shibuya"]["night_avg"] == 23.4
    assert ps["kashiwa"]["night_avg_source"] == "predicted"
    assert ps["kashiwa"]["night_avg"] == 11.8


def test_endpoint_survives_missing_snapshot(app_client, monkeypatch):
    """スナップショットが 404 でも beats_baseline は付き、relative_mae のみ落ちる。"""
    summary = {
        "nights": [{"night_date": "20260709", "overall_live_mae": 6.82, "overall_baseline_mae": 8.07, "stores_scored": 2}],
        "updated_at_utc": "2026-07-09T22:00:00Z",
    }
    daily = {"per_store": {"shibuya": {"live_mae": 11.78, "matched_slots": 40, "live_baseline_mae": 22.29}}}

    import urllib.error

    def _fake_urlopen(req, timeout=10):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "summary.json" in url:
            return _FakeResp(json.dumps(summary).encode())
        if "accuracy/scores/20260709.json" in url:
            return _FakeResp(json.dumps(daily).encode())
        if "snapshots/20260709.json" in url:
            raise urllib.error.HTTPError(url, 404, "not found", {}, None)
        raise AssertionError(f"unexpected storage url: {url}")

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)

    resp = app_client.get("/api/forecast_accuracy")
    assert resp.status_code == 200
    sh = resp.get_json()["live"]["per_store"]["shibuya"]
    assert sh["beats_baseline"] is True
    assert "relative_mae" not in sh
    assert "night_avg" not in sh
