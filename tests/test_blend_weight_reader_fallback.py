"""ForecastService._blend_weight_for() の graceful fallback 専門テスト。

2026-08-22 重み凍結・F-4（plan/FORECAST_FREEZE_DEBATE_FINDINGS.md）で追加した
「非空 weights なのに対象 store_id のキーだけ無ければ 0.5（新店フォールバック）」の
分岐と、既存の graceful fallback（Storage 全体の障害/未作成時は 1.0 のまま）が
両方とも壊れていないことを固定する。

背景: 凍結モードでは accuracy/blend_weights.json（canonical）へ新しいキーが
増えないため、この分岐が無いと新店が凍結解除まで恒久的に純ML(w_ml=1.0)になる。
0.5 は scripts/score_forecasts.py の blend_weight() が観測夜ゼロの店に与える
事前値と同一で、新店の最初の約7日は7日前ベースライン自体が無く
oriental/ml/postprocess.py の blend が該当スロットを skip して結局MLのままなので、
実挙動への影響は最小（詳細は forecast_service.py::_blend_weight_for のdocstring）。

No network / no Storage — 全てプロセス内キャッシュへの直接代入かモックで完結する。
"""

import logging
import time as _time

import pytest


class _NullProvider:
    """ForecastService コンストラクタが要求する provider.logger だけ満たすスタブ。"""

    def __init__(self):
        self.logger = logging.getLogger("test_blend_weight_reader_fallback")


def _make_service(**kwargs):
    from oriental.ml.forecast_service import ForecastService

    return ForecastService(
        provider=_NullProvider(),
        timezone="Asia/Tokyo",
        storage_url=kwargs.pop("storage_url", ""),
        storage_key=kwargs.pop("storage_key", ""),
        **kwargs,
    )


def _seed_cache(service, weights):
    """Storage 往復を避け、プロセス内キャッシュへ直接 weights を注入する。"""
    service._blend_weights = weights
    service._blend_weights_at = _time.time()


def test_nonempty_weights_missing_key_returns_half_new_store_fallback():
    """新店（weights 非空だが対象 store_id のキーだけ無い）→ 0.5。"""
    service = _make_service()
    _seed_cache(service, {"ol_gangnam": 0.6, "shibuya": 0.55})

    assert service._blend_weight_for("ol_new_store") == 0.5


def test_nonempty_weights_existing_key_returns_that_value():
    """対象 store_id のキーがあれば、従来どおりその値をそのまま返す。"""
    service = _make_service()
    _seed_cache(service, {"ol_gangnam": 0.6, "shibuya": 0.55})

    assert service._blend_weight_for("ol_gangnam") == 0.6
    assert service._blend_weight_for("shibuya") == 0.55


def test_empty_weights_map_returns_one_pure_ml():
    """weights が空 {}（未作成/パース結果が空）→ 従来どおり 1.0（全店共通の graceful fallback）。"""
    service = _make_service()
    _seed_cache(service, {})

    assert service._blend_weight_for("ol_gangnam") == 1.0
    assert service._blend_weight_for("ol_new_store") == 1.0


def test_fetch_exception_falls_back_to_one_pure_ml(monkeypatch):
    """Storage 取得そのものが例外を投げても既存の graceful fallback（1.0）を維持する。

    _fetch_blend_weights() 内部は例外を全て握りつぶして空 {} を返す設計
    （docstring 参照）なので、実際に例外を起こす箇所＝ storage_get_bytes を
    モックする（_blend_weight_for / _fetch_blend_weights 自体は try/except で
    包まれていないため、ここを直接 raise させると設計と矛盾するテストになる）。
    """
    import oriental.clients.supabase as supabase_client

    def _boom(*_args, **_kwargs):
        raise RuntimeError("storage unreachable")

    monkeypatch.setattr(supabase_client, "storage_get_bytes", _boom)

    service = _make_service(storage_url="https://example.invalid", storage_key="dummy-key")

    assert service._blend_weight_for("ol_gangnam") == 1.0
    assert service._blend_weight_for("ol_new_store") == 1.0


def test_blend_disabled_returns_one_regardless_of_weights(monkeypatch):
    """FORECAST_BASELINE_BLEND=0 ならキーの有無に関係なく 1.0（既存の無効化スイッチ）。"""
    service = _make_service()
    _seed_cache(service, {"ol_gangnam": 0.6})
    monkeypatch.setenv("FORECAST_BASELINE_BLEND", "0")

    assert service._blend_weight_for("ol_gangnam") == 1.0
    assert service._blend_weight_for("ol_new_store") == 1.0
