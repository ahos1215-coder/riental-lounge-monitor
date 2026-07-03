"""ForecastService.forecast_today のセッション窓（夜 19:00-05:00）決定ロジックのテスト。

回帰対象のバグ: 旧実装は `now.hour < start_h` の場合に日付を1日戻していたため、
05:00-18:59 の間に呼ばれると「前日の(既に終わった)夜」を返してしまっていた
(本番影響: 18:00 JST 日次レポートジョブ、18:10 JST snapshot_forecasts cron)。

正しい仕様: セッションは start_h:00 〜 翌日 end_h:00 (例 19:00-05:00) の1本。
  - now が「実行中セッションの末尾」(00:00 〜 end_h:00 未満) にいる間だけ、
    対象は前日 start_h:00 に開始したセッション。
  - end_h:00 以降 (日中を含め 23:59 まで) は、対象は今日 start_h:00 に開始する
    (これから始まる/現在進行中の) セッション。
"""

from __future__ import annotations

import logging

import pandas as pd
import pytest

from oriental.ml.forecast_service import ForecastService

TZ = "Asia/Tokyo"


class _EmptyProvider:
    """履歴を返さないフェイクプロバイダ。forecast_today は履歴が空でも
    _zero_payload 経由で future_times の形状をそのまま返すため、モデル
    レジストリなしで窓ロジックだけを検証できる。"""

    def __init__(self):
        self.logger = logging.getLogger("test")

    def get_records(self, store_id: str, **_kwargs):
        return []


def make_svc() -> ForecastService:
    return ForecastService(provider=_EmptyProvider(), timezone=TZ, model_registry=None)


def _freeze_now(monkeypatch, jst_naive_str: str) -> pd.Timestamp:
    """pd.Timestamp.now(tz=...) を固定日時にモンキーパッチする。"""
    frozen = pd.Timestamp(jst_naive_str, tz=TZ)

    def _fake_now(tz=None):
        return frozen.tz_convert(tz) if tz is not None else frozen

    monkeypatch.setattr(pd.Timestamp, "now", staticmethod(_fake_now))
    return frozen


@pytest.mark.parametrize(
    ("now_str", "expected_start", "expected_end", "label"),
    [
        # 深夜帯 (00:00-04:59): 実行中セッションの末尾 -> 前日 19:00 開始のセッション
        ("2026-07-02 02:00:00", "2026-07-01 19:00:00", "2026-07-02 05:00:00", "02:00 previous-day start"),
        # 05:00-18:59: 今日 19:00 開始の (これから始まる) セッション
        ("2026-07-02 08:00:00", "2026-07-02 19:00:00", "2026-07-03 05:00:00", "08:00 same-day start"),
        ("2026-07-02 12:00:00", "2026-07-02 19:00:00", "2026-07-03 05:00:00", "12:00 same-day start"),
        ("2026-07-02 18:00:00", "2026-07-02 19:00:00", "2026-07-03 05:00:00", "18:00 same-day start"),
        # 19:00 以降: 今日 19:00 開始の (進行中の) セッション
        ("2026-07-02 20:00:00", "2026-07-02 19:00:00", "2026-07-03 05:00:00", "20:00 same-day start"),
        ("2026-07-02 23:30:00", "2026-07-02 19:00:00", "2026-07-03 05:00:00", "23:30 same-day start"),
    ],
)
def test_forecast_today_window_targets_correct_session(
    monkeypatch, now_str, expected_start, expected_end, label
):
    _freeze_now(monkeypatch, now_str)
    svc = make_svc()

    result = svc.forecast_today(store_id="ol_test", freq_min=60)

    assert result["ok"] is True, label
    data = result["data"]
    assert len(data) > 0, label

    first_ts = pd.Timestamp(data[0]["ts"])
    last_ts = pd.Timestamp(data[-1]["ts"])
    expected_start_ts = pd.Timestamp(expected_start, tz=TZ)
    expected_end_ts = pd.Timestamp(expected_end, tz=TZ)

    assert first_ts == expected_start_ts, f"{label}: start mismatch"
    # inclusive="left" なので最終スロットは end の1周期前
    assert last_ts < expected_end_ts, f"{label}: last slot should be before end"
    assert last_ts + pd.Timedelta(minutes=60) == expected_end_ts, f"{label}: end mismatch"


def test_forecast_today_window_respects_custom_start_end_hours(monkeypatch):
    """start_h/end_h をデフォルト以外にしても同じロジックで動くことを確認する
    (ハードコードされた 19/5 に依存していないことの回帰防止)。"""
    _freeze_now(monkeypatch, "2026-07-02 01:00:00")  # end_h=3 の「末尾」帯
    svc = make_svc()

    result = svc.forecast_today(store_id="ol_test", freq_min=60, start_h=21, end_h=3)

    assert result["ok"] is True
    data = result["data"]
    first_ts = pd.Timestamp(data[0]["ts"])
    last_ts = pd.Timestamp(data[-1]["ts"])

    assert first_ts == pd.Timestamp("2026-07-01 21:00:00", tz=TZ)
    assert last_ts + pd.Timedelta(minutes=60) == pd.Timestamp("2026-07-02 03:00:00", tz=TZ)


def test_forecast_today_window_custom_hours_daytime_targets_upcoming_session(monkeypatch):
    _freeze_now(monkeypatch, "2026-07-02 10:00:00")  # end_h=3 より後 -> 今日開始
    svc = make_svc()

    result = svc.forecast_today(store_id="ol_test", freq_min=60, start_h=21, end_h=3)

    assert result["ok"] is True
    data = result["data"]
    first_ts = pd.Timestamp(data[0]["ts"])
    last_ts = pd.Timestamp(data[-1]["ts"])

    assert first_ts == pd.Timestamp("2026-07-02 21:00:00", tz=TZ)
    assert last_ts + pd.Timedelta(minutes=60) == pd.Timestamp("2026-07-03 03:00:00", tz=TZ)
