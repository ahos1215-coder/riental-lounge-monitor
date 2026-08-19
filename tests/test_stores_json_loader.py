"""stores.json の読み手を1本化(load_stores_rows)しても挙動が変わらないことの番犬。

守りたい不変条件は3つ:
  1. `_preload_models` が巡回する店舗集合 = ALL_STORE_IDS（独自 stores.json 読み +
     11店ハードコード fallback を廃止したので、二重管理による取りこぼしが起きない）。
  2. `weather_forecast._store_coords()` は「読めない/壊れている」場合でも **例外を外に
     出さず {} を返す**（weather_forecast の docstring にある安全設計。ここが崩れると
     予測サービス全体が天気取得の失敗で落ちる）。
  3. `load_stores_rows()` は list[dict] 以外の JSON（dict/文字列/壊れたJSON/欠損ファイル）
     を全て [] に落とす（呼び出し側の `.get()` が AttributeError を投げないため）。
"""

from __future__ import annotations

import pytest

from oriental.ml import weather_forecast
from oriental.utils import stores as stores_mod
from oriental.utils.stores import ALL_STORE_IDS


# --- 1. _preload_models が ALL_STORE_IDS を巡回する -----------------------


class _FakeRegistry:
    def __init__(self) -> None:
        self.seen: list[str] = []

    def get_bundle(self, store_id: str):
        self.seen.append(store_id)
        return object()


def test_preload_models_iterates_all_store_ids(monkeypatch):
    from oriental import _preload_models, create_app
    from oriental.config import AppConfig

    monkeypatch.setenv("ENABLE_FORECAST", "1")
    # create_app が別スレッドで preload を走らせると二重集計になるので止める。
    monkeypatch.setenv("DISABLE_MODEL_PRELOAD", "1")
    app = create_app(AppConfig.from_env())

    registry = _FakeRegistry()

    class _FakeService:
        model_registry = registry

    import oriental.ml.forecast_service as fs

    monkeypatch.setattr(fs.ForecastService, "from_app", staticmethod(lambda _app: _FakeService()))

    _preload_models(app)

    assert registry.seen == list(ALL_STORE_IDS)


# --- 2/3. stores.json が壊れていても {} / [] に落ちる ---------------------


@pytest.fixture(autouse=True)
def _reset_weather_cache():
    weather_forecast._coords_cache = None
    yield
    weather_forecast._coords_cache = None


@pytest.mark.parametrize(
    "content",
    [
        None,  # ファイル自体が存在しない
        "{ this is not json",  # 壊れた JSON
        '{"store_id": "ol_shibuya"}',  # list ではなく dict
        '"just a string"',
        "[1, 2, 3]",  # list だが要素が dict でない
    ],
)
def test_broken_stores_json_never_raises(monkeypatch, tmp_path, content):
    path = tmp_path / "stores.json"
    if content is not None:
        path.write_text(content, encoding="utf-8")

    monkeypatch.setattr(stores_mod, "STORES_JSON_PATH", path)

    assert stores_mod.load_stores_rows() == []
    # weather_forecast は「失敗時 {} を返し例外を外に漏らさない」が絶対条件。
    assert weather_forecast._store_coords() == {}


def test_load_stores_rows_returns_dict_rows_for_real_file():
    rows = stores_mod.load_stores_rows()
    assert rows, "frontend/src/data/stores.json が読めていない"
    assert all(isinstance(r, dict) for r in rows)
    assert {r.get("store_id") for r in rows} == set(ALL_STORE_IDS)


def test_store_coords_covers_every_store():
    """座標は全店分そろっている（1店でも欠けると天気注入がその店だけ死ぬ）。"""
    coords = weather_forecast._store_coords()
    assert set(coords) == set(ALL_STORE_IDS)
