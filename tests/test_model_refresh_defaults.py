"""番犬: モデル再取得ウィンドウ（FORECAST_MODEL_REFRESH_SEC / MODEL_REFRESH_BATCH）の既定値。

2026-09-09 egress 削減。モデルは日次学習（GHA train-ml-model.yml, 05:30 JST）で
**1日1回しか変わらない**のに、旧既定の 900秒（15分）は sweep のたびに metadata.json
（実測 320,848 B）を取り直していた: 86400/900 = 96窓/日 ≒ 29.4 MiB/日。
10800秒（3時間）なら 8窓/日 ≒ 2.4 MiB/日（-92%）。

ただしウィンドウを延ばすと、1窓あたり MODEL_REFRESH_BATCH 店ずつしか新モデルを
拾わない sweep の全店伝播が遅くなる。ここで固定するのはその釣り合い:
  ceil(42店 / batch) 窓 × refresh_sec ≦ 9時間 → 05:30 の学習が遅くとも 14:30 JST に
  全店へ行き渡る＝サイトのピーク（19:00 以降の夜窓）より前に必ず終わる。
（旧 batch=10 のままだと ceil(42/10)=5窓 = 15時間で 20:30 着＝ピークに食い込む。
  だから batch も 10→14 に上げた。）
"""

from __future__ import annotations

import logging
import math

import pytest

from oriental.config import AppConfig
from oriental.ml.model_registry import ForecastModelRegistry
from oriental.utils.stores import ALL_STORE_IDS

_DEFAULT_REFRESH_SEC = 10800
_DEFAULT_REFRESH_BATCH = 14
# 05:30 の学習が「その日の夜窓（19:00〜）」に間に合うための余裕。
_TRAIN_HOUR_JST = 5.5
_PEAK_HOUR_JST = 19.0


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    """.env / .env.local の値に引きずられずに「既定」を見る。"""
    for name in ("FORECAST_MODEL_REFRESH_SEC", "MODEL_REFRESH_BATCH"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("FORECAST_MODEL_CACHE_DIR", str(tmp_path))
    return tmp_path


class _StubApp:
    """`ForecastModelRegistry.from_app` が触るぶんだけの app。"""

    def __init__(self, cfg: AppConfig) -> None:
        self.config = {"APP_CONFIG": cfg}
        self.logger = logging.getLogger("test")


def test_refresh_sec_default_is_three_hours(clean_env):
    cfg = AppConfig.from_env()
    assert cfg.forecast_model_refresh_sec == _DEFAULT_REFRESH_SEC, (
        "モデルは日次学習で1日1回しか変わらない。15分ごとに metadata.json を"
        "取り直す理由がない（旧 900秒 = 96窓/日 ≒ 29.4 MiB/日）"
    )


def test_refresh_sec_env_override_still_works(clean_env, monkeypatch):
    """緊急時に短く戻せること（既定を変えても逃がし弁は残す）。"""
    monkeypatch.setenv("FORECAST_MODEL_REFRESH_SEC", "900")
    assert AppConfig.from_env().forecast_model_refresh_sec == 900


def test_refresh_batch_default(clean_env):
    registry = ForecastModelRegistry.from_app(_StubApp(AppConfig.from_env()))
    assert registry.refresh_batch == _DEFAULT_REFRESH_BATCH
    assert registry.refresh_sec == _DEFAULT_REFRESH_SEC


def test_full_propagation_finishes_before_the_evening_peak(clean_env):
    """全42店に新モデルが行き渡るまでの最悪値が、夜のピークより前に収まること。

    sweep は1窓につき最大 refresh_batch 店しか再パースしない（トリガー店舗も
    この予算を1つ消費する）。したがって全店伝播に要する窓数は ceil(42 / batch)。
    """
    registry = ForecastModelRegistry.from_app(_StubApp(AppConfig.from_env()))
    windows = math.ceil(len(ALL_STORE_IDS) / registry.refresh_batch)
    worst_case_hours = windows * registry.refresh_sec / 3600

    assert windows == 3
    assert worst_case_hours == 9.0
    assert _TRAIN_HOUR_JST + worst_case_hours < _PEAK_HOUR_JST, (
        f"05:30 の学習が全店に行き渡るのに最悪 {worst_case_hours} 時間かかると"
        "19時のピークに食い込む。refresh_sec を延ばすなら batch も上げること"
    )
