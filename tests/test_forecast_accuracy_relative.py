"""/api/forecast_accuracy の相対精度フィールド（additive）のテスト。

精度バッジを「絶対人数の MAE」ではなく「店舗規模に対する相対性能」で判定できるよう、
バックエンドが per_store に付与する 3 フィールドを検証する:
  - beats_baseline: live_mae < live_baseline_mae（ナイーブ基準に勝っているか）
  - night_avg:      想定夜間来客数（予測スナップショットの総数平均＝相対誤差の分母）
  - relative_mae:   live_mae / night_avg（店舗規模で正規化した相対誤差）

純関数 (_night_avg_by_store / _augment_relative_fields) はネットワーク無しで、
エンドポイントは _storage_get（urllib）をモックして検証する。既存キー（mae_7d 等）が
壊れていないことも確認する（後方互換＝追加のみ）。
"""

from __future__ import annotations

import json

import pytest

from oriental import create_app
from oriental.routes import forecast as fc


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
    assert sh["relative_mae"] == pytest.approx(round(11.78 / 44.8, 3))
    # 既存キーが残っていること
    assert sh["live_mae"] == 11.78 and sh["ml_vs_baseline_live_pct"] == 47.2

    # kashiwa: ナイーブ基準に負け -> beats_baseline False（バッジは参考値に丸められる根拠）
    ka = ps["kashiwa"]
    assert ka["beats_baseline"] is False
    assert ka["relative_mae"] == pytest.approx(round(6.99 / 11.8, 3))


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
