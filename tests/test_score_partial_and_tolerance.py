"""score_forecasts.main() の「部分採点を正規パスへ昇格させない」「勝敗は両方を持つ店で比べる」
「ノイズ級の負けでは失敗にしない」を固定する（すべてモック／ネットワーク無し）。

背景（2026-10 の実測）:
  - 2026-10-30 の夜はオリエンタル37店の logs が無く、相席屋5店だけが採点された。これが
    accuracy/scores/20261030.json と summary.json に載り、/api/forecast_accuracy が「直近夜5店」を返した。
  - 2026-10-13 の夜は live 7.61 vs baseline 7.59（+0.3%）でジョブが落ちた（ノイズ）。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

import scripts.score_forecasts as sf


def _night_context():
    night_date = (datetime.now(sf.JST) - timedelta(days=1)).strftime("%Y%m%d")
    base = datetime.strptime(night_date, "%Y%m%d").replace(tzinfo=sf.JST)
    slot = base.replace(hour=23, minute=0, second=0, microsecond=0)
    start_iso = base.replace(hour=19, minute=0, second=0, microsecond=0).astimezone(sf.timezone.utc).isoformat()
    return night_date, slot, start_iso


def _run_main(monkeypatch, stores: dict[str, tuple[float | None, float | None]], *, pred: float = 50.0):
    """stores: slug -> (今夜の実測, 先週の実測)。None はその窓の logs が無い店。

    戻り値: (main() の終了コード, _storage_put に渡された path の一覧)
    """
    monkeypatch.setattr(sf, "_load_env", lambda: None)
    monkeypatch.setenv("SUPABASE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "dummy")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.delenv("ACCURACY_FAIL_ON_BASELINE_LOSS", raising=False)

    night_date, slot, start_iso = _night_context()
    snapshot = {
        "expected_slugs": list(stores),
        "by_slug": {s: [{"ts": slot.isoformat(), "total_pred": pred}] for s in stores},
    }
    puts: list[str] = []

    def fake_get(bucket, path, url, key):
        if path.startswith("accuracy/snapshots/"):
            return json.dumps(snapshot).encode()
        return None

    def fake_put(bucket, path, payload, url, key, *a, **k):
        puts.append(path)

    def fake_actuals(url, key, store_id, s_iso, e_iso):
        slug = store_id if store_id.startswith("ay_") else store_id[len("ol_"):]
        now_v, prev_v = stores[slug]
        if s_iso == start_iso:
            return [] if now_v is None else [{"ts": slot.isoformat(), "total": float(now_v)}]
        return [] if prev_v is None else [{"ts": (slot - timedelta(days=7)).isoformat(), "total": float(prev_v)}]

    monkeypatch.setattr(sf, "_storage_get", fake_get)
    monkeypatch.setattr(sf, "_storage_put", fake_put)
    monkeypatch.setattr(sf, "_alert", lambda msg: None)
    monkeypatch.setattr(sf, "_fetch_actuals", fake_actuals)
    return sf.main(), puts, night_date


def test_採点できた店が9割未満の夜は正規パスにもsummaryにも昇格しない(monkeypatch):
    # 10店中2店だけ実測がある（＝オリエンタルの logs が無かった夜の再現）
    stores = {f"s{i}": (None, None) for i in range(8)}
    stores.update({"ay_a": (48.0, 10.0), "ay_b": (48.0, 10.0)})
    code, puts, night = _run_main(monkeypatch, stores)

    assert code == 1  # 嘘の精度を出さない代わりに、ジョブは従来どおり失敗させる（鳴らす）
    assert f"accuracy/scores/_partial/{night}.json" in puts
    assert f"accuracy/scores/{night}.json" not in puts
    assert "accuracy/scores/summary.json" not in puts


def test_全店採点できた夜は従来どおり正規パスとsummaryへ書く(monkeypatch):
    stores = {f"s{i}": (48.0, 10.0) for i in range(10)}  # ML 勝ち
    code, puts, night = _run_main(monkeypatch, stores)

    assert code == 0
    assert f"accuracy/scores/{night}.json" in puts
    assert "accuracy/scores/summary.json" in puts
    assert not any("_partial" in p for p in puts)


def test_ノイズ級の負け_許容内_では失敗にしない(monkeypatch):
    # 実測10・ML予測50(誤差40)・先週49(誤差39) → +2.6% の負け。既定の許容 5% 以内。
    code, _puts, _night = _run_main(monkeypatch, {"shibuya": (10.0, 49.0)})
    assert code == 0


def test_許容0にすれば従来どおり1でも負ければ失敗(monkeypatch):
    monkeypatch.setenv("ACCURACY_BASELINE_LOSS_TOLERANCE_PCT", "0")
    code, _puts, _night = _run_main(monkeypatch, {"shibuya": (10.0, 49.0)})
    assert code == 1


def test_許容を超える負けは失敗(monkeypatch):
    # ML 誤差40 vs 先週誤差2 → +1900%
    code, _puts, _night = _run_main(monkeypatch, {"shibuya": (10.0, 12.0)})
    assert code == 1


def test_勝敗は両方を持つ店だけで比べる_先週が欠測の店に引っ張られない(monkeypatch):
    # A: ML誤差1 vs 先週誤差5（ML勝ち）。B: 先週の logs が無く baseline 無し（ML誤差30）。
    # 旧: overall=15.5 vs overall_baseline=5.0（A のみ）→ 偽の負け。新: paired 1 vs 5 → 勝ち。
    code, _puts, _night = _run_main(monkeypatch, {"a": (49.0, 44.0), "b": (20.0, None)})
    assert code == 0


@pytest.mark.parametrize(
    "raw, expected",
    [("", 0.05), ("abc", 0.05), ("-3", 0.05), ("101", 0.05), ("nan", 0.05), ("0", 0.0), ("12.5", 0.125)],
)
def test_許容率の環境変数の読み方(monkeypatch, raw, expected):
    monkeypatch.setenv("ACCURACY_BASELINE_LOSS_TOLERANCE_PCT", raw)
    assert sf._baseline_loss_tolerance() == pytest.approx(expected)


def test_アラート判定は従来の呼び方でも変わらない():
    alerts, _cov = sf._collect_accuracy_alerts(
        overall=6.0, overall_baseline=5.0, summary_nights=[{"night_date": "20260818", "overall_live_mae": 6.0}],
        expected=3, stores_scored=3,
    )
    assert len(alerts) == 1 and "NOT beating the naive baseline" in alerts[0]
